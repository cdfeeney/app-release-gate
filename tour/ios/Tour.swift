import XCTest

// app-release-gate: generic screenshot tour for any iOS app.
//
// This file is COPIED into each app's UI test target unchanged; the gate verifies the copy matches
// the kit (scripts/verify-copy.py). Per-app behaviour lives in Gate/tour.json beside this file.
//
// What it does: launches the app with the fixtures the manifest names, follows the manifest's steps
// (tap, wait, scroll, type), and at every stop writes a PNG screenshot plus the accessibility tree
// (app.debugDescription) to TOUR_OUT. Every tap records whether the screen changed. Deterministic:
// no LLM, no synthetic taps; XCUITest drives real controls.
//
// Paths: TOUR_PATH / TOUR_OUT come from the environment (xcodebuild passes TEST_RUNNER_TOUR_PATH as
// TOUR_PATH); otherwise Gate/tour.json and Gate/out beside this file. On the simulator the test
// runner reads and writes host paths directly (the same mechanism snapshot-testing libraries use
// to write reference images beside the test file via #filePath).
@MainActor
final class TourTests: XCTestCase {
    struct Manifest: Decodable {
        var launchArguments: [String]?
        var launchEnvironment: [String: String]?
        var fixtureEnvKey: String?
        var fixtures: [Fixture]?
        var flows: [Flow]
    }

    struct Fixture: Decodable {
        var name: String
        var file: String
        var setDateKeyToToday: String?
        var week: Int?
    }

    struct Flow: Decodable {
        var name: String
        var steps: [Step]
    }

    struct Step: Decodable {
        var tap: String?
        var tapMatching: String?
        var waitFor: String?
        var scrollToBottom: Bool?
        var swipe: String?
        var shot: String?
        var expectChange: Bool?
        var typeText: String?
        var sleep: Double?
        var optional: Bool?
    }

    private static let maxScrollStops = 25

    private var outDir: URL!
    private var shotIndex = 0
    private var index: [[String: Any]] = []
    private var taps: [[String: Any]] = []
    private var problems: [String] = []

    private var gateDir: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Gate")
    }

    func testTour() throws {
        continueAfterFailure = true
        let env = ProcessInfo.processInfo.environment
        let manifestURL = env["TOUR_PATH"].map { URL(fileURLWithPath: $0) } ?? gateDir.appendingPathComponent("tour.json")
        outDir = env["TOUR_OUT"].map { URL(fileURLWithPath: $0) } ?? gateDir.appendingPathComponent("out")
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: manifestURL))

        var fixtures: [Fixture?] = (manifest.fixtures ?? []).map { Optional($0) }
        if fixtures.isEmpty { fixtures = [nil] }
        for fixture in fixtures {
            let app = XCUIApplication()
            app.launchArguments = (manifest.launchArguments ?? []).map { $0.replacingOccurrences(of: "{uuid}", with: UUID().uuidString) }
            var environment = manifest.launchEnvironment ?? [:]
            if let fixture = fixture, let key = manifest.fixtureEnvKey {
                environment[key] = try fixtureJSON(fixture, relativeTo: manifestURL.deletingLastPathComponent())
            }
            app.launchEnvironment = environment
            app.launch()
            for flow in manifest.flows {
                run(flow, fixture: fixture?.name ?? "default", in: app)
            }
            app.terminate()
        }
        if index.isEmpty { problems.append("the tour captured no screens") }
        try write(json: index, name: "index.json")
        try write(json: taps, name: "taps.json")
        try write(json: ["problems": problems, "fixtures": fixtures.map { $0?.name ?? "default" }, "screens": index.count], name: "summary.json")
        XCTAssertTrue(problems.isEmpty, problems.joined(separator: "\n"))
    }

    // MARK: steps

    private func run(_ flow: Flow, fixture: String, in app: XCUIApplication) {
        for (i, step) in flow.steps.enumerated() {
            let label = "\(fixture)/\(flow.name)/step\(i)"
            if let id = step.waitFor {
                if !element(id, in: app).waitForExistence(timeout: 15) { note("\(label): \(id) never appeared", optional: step.optional) }
            }
            if let seconds = step.sleep { Thread.sleep(forTimeInterval: seconds) }
            if let swipe = step.swipe {
                if swipe == "down" { app.swipeDown(velocity: .slow) } else { app.swipeUp(velocity: .slow) }
            }
            var target = step.tap
            if target == nil, let pattern = step.tapMatching {
                target = firstIdentifier(matching: pattern, in: app)
                if target == nil { note("\(label): no element matches \(pattern)", optional: step.optional) }
            }
            if let id = target {
                tap(id, label: label, expectChange: step.expectChange ?? true, optional: step.optional, in: app)
            }
            if let text = step.typeText { app.typeText(text) }
            // Every capture names its screen; unnamed scrolls get a unique name so rules never merge two UI states.
            let screen = step.shot ?? "step\(i)"
            if step.scrollToBottom == true {
                scrollToBottom(fixture: fixture, flow: flow.name, screen: screen, label: label, in: app)
            } else if step.shot != nil {
                capture(fixture: fixture, flow: flow.name, screen: screen, name: screen, in: app)
            }
        }
    }

    private func tap(_ id: String, label: String, expectChange: Bool, optional: Bool?, in app: XCUIApplication) {
        let target = element(id, in: app)
        reveal(target, in: app)
        guard target.exists, target.isHittable else {
            note("\(label): \(id) not tappable (exists=\(target.exists))", optional: optional)
            return
        }
        let before = normalized(app.debugDescription)
        target.tap()
        var changed = false
        for _ in 0..<12 {
            if normalized(app.debugDescription) != before { changed = true; break }
            Thread.sleep(forTimeInterval: 0.25)
        }
        taps.append(["identifier": id, "step": label, "changed": changed, "expected": expectChange])
        if expectChange && !changed { note("\(label): tapping \(id) changed nothing on screen", optional: optional) }
    }

    /// Capture, swipe up, capture again, until the tree stops changing. Every state that exists is captured.
    private func scrollToBottom(fixture: String, flow: String, screen: String, label: String, in app: XCUIApplication) {
        var last = ""
        var settled = false
        for position in 1...Self.maxScrollStops {
            capture(fixture: fixture, flow: flow, screen: screen, name: "\(screen)-\(String(format: "%02d", position))", in: app)
            let now = normalized(app.debugDescription)
            if now == last { settled = true; break }
            last = now
            app.swipeUp(velocity: .slow)
            Thread.sleep(forTimeInterval: 0.4)
        }
        if !settled { note("\(label): \(screen) never stopped scrolling after \(Self.maxScrollStops) swipes; bottom not captured", optional: false) }
    }

    private func capture(fixture: String, flow: String, screen: String, name: String, in app: XCUIApplication) {
        shotIndex += 1
        let base = String(format: "%03d", shotIndex) + "-\(fixture)-\(flow)-\(name)"
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let tree = app.debugDescription
        do {
            try png.write(to: outDir.appendingPathComponent(base + ".png"))
            try tree.write(to: outDir.appendingPathComponent(base + ".tree.txt"), atomically: true, encoding: .utf8)
        } catch {
            note("capture \(base) failed: \(error)", optional: false)
        }
        if png.isEmpty || tree.isEmpty { note("capture \(base) is empty", optional: false) }
        index.append(["n": shotIndex, "fixture": fixture, "flow": flow, "screen": screen, "name": name,
                      "png": base + ".png", "tree": base + ".tree.txt",
                      "window": ["width": Double(app.frame.width), "height": Double(app.frame.height)]])
    }

    // MARK: helpers

    private func element(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func firstIdentifier(matching pattern: String, in app: XCUIApplication) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        for line in app.debugDescription.components(separatedBy: "\n") {
            guard let range = line.range(of: "identifier: '") else { continue }
            let rest = line[range.upperBound...]
            guard let end = rest.firstIndex(of: "'") else { continue }
            let id = String(rest[..<end])
            if regex.firstMatch(in: id, range: NSRange(id.startIndex..., in: id)) != nil { return id }
        }
        return nil
    }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<18 {
            if target.exists && target.isHittable { return }
            if target.exists && target.frame.height > 0 && target.frame.minY < app.frame.minY + 100 {
                app.swipeDown(velocity: .slow)
            } else {
                app.swipeUp(velocity: .slow)
            }
        }
    }

    private func normalized(_ tree: String) -> String {
        // Drop object addresses and pids so two dumps of the same screen compare equal.
        tree.replacingOccurrences(of: "0x[0-9a-fA-F]+", with: "0x", options: .regularExpression)
            .replacingOccurrences(of: "pid: [0-9]+", with: "pid", options: .regularExpression)
    }

    private func note(_ problem: String, optional: Bool?) {
        if optional == true { return }
        problems.append(problem)
    }

    private func fixtureJSON(_ fixture: Fixture, relativeTo dir: URL) throws -> String {
        let data = try Data(contentsOf: dir.appendingPathComponent(fixture.file))
        guard let key = fixture.setDateKeyToToday, var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return String(decoding: data, as: UTF8.self)
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone.current
        object[key] = formatter.string(from: Date())
        return String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self)
    }

    private func write(json: Any, name: String) throws {
        try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys]).write(to: outDir.appendingPathComponent(name))
    }
}
