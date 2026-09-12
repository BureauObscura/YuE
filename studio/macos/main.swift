import AppKit
import Foundation
import WebKit
import Darwin

final class StudioDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private var window: NSWindow!
    private var webView: WKWebView?
    private var server: Process?
    private var serverLog: FileHandle?
    private var logURL: URL?
    private var origin: URL?
    private var quitting = false
    private var startupGeneration = 0
    private var downloadTargets: [ObjectIdentifier: (temporary: URL, destination: URL)] = [:]
    private var statusLabel: NSTextField?
    private let dataDirectory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/YuE Studio", isDirectory: true)

    func applicationDidFinishLaunching(_ notification: Notification) {
        makeMenus()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1360, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "YuE Studio"
        window.minSize = NSSize(width: 1000, height: 720)
        window.setFrameAutosaveName("YuEStudioWindow")
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.backgroundColor = NSColor(red: 245.0 / 255, green: 243.0 / 255, blue: 239.0 / 255, alpha: 1)
        window.appearance = NSAppearance(named: .aqua)
        window.center()
        showStatus("Opening your studio", detail: "Starting the local service. Your library stays on this Mac.", failed: false)
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        startServer()
    }

    private func makeMenus() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About YuE Studio", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Open Library Folder", action: #selector(openLibrary), keyEquivalent: "")
        appMenu.addItem(withTitle: "Open Service Log", action: #selector(openLog), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide YuE Studio", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit YuE Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)

        let editItem = NSMenuItem()
        editItem.title = "Edit"
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)

        let viewItem = NSMenuItem()
        viewItem.title = "View"
        let viewMenu = NSMenu(title: "View")
        viewMenu.addItem(withTitle: "Reload Studio", action: #selector(reloadStudio), keyEquivalent: "r")
        viewMenu.addItem(.separator())
        viewMenu.addItem(withTitle: "Zoom In", action: #selector(zoomIn), keyEquivalent: "+")
        let zoomAlternate = viewMenu.addItem(withTitle: "Zoom In", action: #selector(zoomIn), keyEquivalent: "=")
        zoomAlternate.isAlternate = true
        viewMenu.addItem(withTitle: "Zoom Out", action: #selector(zoomOut), keyEquivalent: "-")
        viewMenu.addItem(withTitle: "Actual Size", action: #selector(resetZoom), keyEquivalent: "0")
        viewItem.submenu = viewMenu
        menu.addItem(viewItem)
        NSApplication.shared.mainMenu = menu
    }

    private func showStatus(_ title: String, detail: String, failed: Bool) {
        let content = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        let heading = NSTextField(labelWithString: title)
        heading.font = .systemFont(ofSize: 27, weight: .semibold)
        heading.textColor = .labelColor
        let message = NSTextField(wrappingLabelWithString: detail)
        message.alignment = .center
        message.font = .systemFont(ofSize: 14)
        message.textColor = .secondaryLabelColor
        statusLabel = message
        stack.addArrangedSubview(heading)
        stack.addArrangedSubview(message)
        if failed {
            let buttons = NSStackView()
            buttons.spacing = 10
            buttons.addArrangedSubview(NSButton(title: "Try Again", target: self, action: #selector(retryStartup)))
            buttons.addArrangedSubview(NSButton(title: "Open Log", target: self, action: #selector(openLog)))
            buttons.addArrangedSubview(NSButton(title: "Python Setup", target: self, action: #selector(openPythonSetup)))
            stack.addArrangedSubview(buttons)
        } else {
            let progress = NSProgressIndicator()
            progress.style = .spinning
            progress.controlSize = .small
            progress.startAnimation(nil)
            stack.addArrangedSubview(progress)
        }
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            stack.widthAnchor.constraint(equalToConstant: 620)
        ])
        window.contentView = content
    }

    private func findPython() -> URL? {
        var candidates = ["/opt/homebrew/bin/python3.12", "/usr/local/bin/python3.12", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        for path in (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":") {
            candidates.append(String(path) + "/python3.12")
            candidates.append(String(path) + "/python3")
        }
        var seen = Set<String>()
        for candidate in candidates where seen.insert(candidate).inserted {
            guard FileManager.default.isExecutableFile(atPath: candidate) else { continue }
            let probe = Process()
            probe.executableURL = URL(fileURLWithPath: candidate)
            probe.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"]
            probe.standardOutput = FileHandle.nullDevice
            probe.standardError = FileHandle.nullDevice
            do {
                try probe.run()
                probe.waitUntilExit()
                if probe.terminationStatus == 0 { return URL(fileURLWithPath: candidate) }
            } catch { continue }
        }
        return nil
    }

    private func availablePort() throws -> UInt16 {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { throw StudioError.message("Could not create a local network socket.") }
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard result == 0 else { throw StudioError.message("Could not reserve an available localhost port.") }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let inspected = withUnsafeMutablePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(descriptor, $0, &length) }
        }
        guard inspected == 0 else { throw StudioError.message("Could not read the localhost port.") }
        return UInt16(bigEndian: address.sin_port)
    }

    private func startServer() {
        startupGeneration += 1
        let generation = startupGeneration
        guard let resources = Bundle.main.resourceURL else {
            startupFailed("The app bundle is incomplete. Rebuild it with studio/macos/build_app.py.")
            return
        }
        let script = resources.appendingPathComponent("server/server.py")
        let web = resources.appendingPathComponent("web")
        guard FileManager.default.fileExists(atPath: script.path),
              FileManager.default.fileExists(atPath: web.appendingPathComponent("index.html").path) else {
            startupFailed("The service or interface files are missing from this app. Rebuild it with studio/macos/build_app.py.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let python = self.findPython()
            DispatchQueue.main.async { [weak self] in
                guard let self, !self.quitting, generation == self.startupGeneration else { return }
                guard let python else {
                    self.startupFailed("YuE Studio needs Python 3.10 or newer. Install Python 3.12 from python.org, or run ‘brew install python@3.12’ in Terminal, then choose Try Again. Music models are installed separately.")
                    return
                }
                do {
                    let logs = self.dataDirectory.appendingPathComponent("Logs", isDirectory: true)
                    try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
                    let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
                    self.logURL = logs.appendingPathComponent("studio-\(stamp)-\(UUID().uuidString.prefix(8)).log")
                    FileManager.default.createFile(atPath: self.logURL!.path, contents: nil)
                    self.serverLog = try FileHandle(forWritingTo: self.logURL!)
                    let port = try self.availablePort()
                    self.origin = URL(string: "http://127.0.0.1:\(port)")!
                    let process = Process()
                    process.executableURL = python
                    process.arguments = ["-u", script.path, "--host", "127.0.0.1", "--port", String(port), "--data-dir", self.dataDirectory.path, "--web-dir", web.path, "--no-open"]
                    var environment = ProcessInfo.processInfo.environment
                    environment["PYTHONUNBUFFERED"] = "1"
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    // The interface service uses only its bundled stdlib Python files.
                    // The worker adds bundled src/ to its own import path separately.
                    environment.removeValue(forKey: "PYTHONPATH")
                    environment["YUE_STUDIO_REPO"] = resources.path
                    process.currentDirectoryURL = self.dataDirectory
                    process.environment = environment
                    process.standardInput = FileHandle.nullDevice
                    process.standardOutput = self.serverLog
                    process.standardError = self.serverLog
                    process.terminationHandler = { [weak self] finished in
                        DispatchQueue.main.async { [weak self] in
                            guard let self, !self.quitting, generation == self.startupGeneration else { return }
                            self.startupFailed("The local service stopped (exit \(finished.terminationStatus)). Open the log for details, then choose Try Again. Your saved library is still in Application Support.")
                        }
                    }
                    self.server = process
                    self.log("Starting service with Python: \(python.path)")
                    self.log("Bundled service: \(script.path)")
                    self.log("Working directory: \(self.dataDirectory.path)")
                    try process.run()
                    self.log("Service process started: PID \(process.processIdentifier), port \(port)")
                    self.waitForService(generation: generation, deadline: Date().addingTimeInterval(45))
                } catch {
                    self.startupFailed("Could not start YuE Studio: \(error.localizedDescription)")
                }
            }
        }
    }

    private func waitForService(generation: Int, deadline: Date) {
        guard !quitting, generation == startupGeneration, let origin, let server, server.isRunning else { return }
        var request = URLRequest(url: origin.appendingPathComponent("api/bootstrap"))
        // Bootstrap may perform one bounded runtime check before responding.
        request.timeoutInterval = 25
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async { [weak self] in
                guard let self, !self.quitting, generation == self.startupGeneration, self.server?.isRunning == true else { return }
                let isReady = (response as? HTTPURLResponse)?.statusCode == 200 && data.flatMap { try? JSONSerialization.jsonObject(with: $0) } is [String: Any]
                if isReady {
                    self.log("Local service is ready; opening the interface.")
                    self.showStudio()
                } else if Date() >= deadline {
                    self.log("Service readiness check timed out.")
                    self.startupGeneration += 1
                    self.server?.terminate()
                    self.startupFailed("The local service did not become ready within 45 seconds. Open the log to check the cause, then choose Try Again.")
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
                        self?.waitForService(generation: generation, deadline: deadline)
                    }
                }
            }
        }.resume()
    }

    private func showStudio() {
        guard let origin else { return }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: window.contentView?.bounds ?? .zero, configuration: configuration)
        view.autoresizingMask = [.width, .height]
        view.navigationDelegate = self
        view.uiDelegate = self
        view.allowsBackForwardNavigationGestures = false
        view.setValue(false, forKey: "drawsBackground")
        self.webView = view
        window.contentView = view
        window.makeFirstResponder(view)
        view.load(URLRequest(url: origin))
    }

    private func startupFailed(_ detail: String) {
        log(detail)
        showStatus("YuE Studio couldn’t open", detail: detail, failed: true)
    }

    private func log(_ message: String) {
        let line = "[launcher \(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        if let data = line.data(using: .utf8) { try? serverLog?.write(contentsOf: data) }
    }

    private func sameOrigin(_ url: URL) -> Bool {
        guard let origin else { return false }
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if sameOrigin(url) || url.scheme == "blob" {
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
        } else {
            decisionHandler(.cancel)
            if ["http", "https", "mailto"].contains(url.scheme ?? ""), navigationAction.navigationType == .linkActivated {
                NSWorkspace.shared.open(url)
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let response = navigationResponse.response as? HTTPURLResponse
        let attachment = response?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("attachment") == true
        decisionHandler(attachment || !navigationResponse.canShowMIMEType ? .download : .allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url {
            if sameOrigin(url) { webView.load(navigationAction.request) }
            else if ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.title = "Export from YuE Studio"
        panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { [weak self] result in
            guard let self, result == .OK, let target = panel.url else { completionHandler(nil); return }
            do {
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent("YuEStudio-\(UUID().uuidString)", isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let temporary = folder.appendingPathComponent("download")
                self.downloadTargets[ObjectIdentifier(download)] = (temporary, target)
                completionHandler(temporary)
            } catch {
                completionHandler(nil)
                self.showError("Could not prepare the export", detail: error.localizedDescription)
            }
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let files = downloadTargets.removeValue(forKey: ObjectIdentifier(download)) else { return }
        do {
            if FileManager.default.fileExists(atPath: files.destination.path) {
                _ = try FileManager.default.replaceItemAt(files.destination, withItemAt: files.temporary)
            } else {
                try FileManager.default.moveItem(at: files.temporary, to: files.destination)
            }
            try? FileManager.default.removeItem(at: files.temporary.deletingLastPathComponent())
            NSWorkspace.shared.activateFileViewerSelecting([files.destination])
        } catch {
            showError("Could not save the export", detail: "\(error.localizedDescription)\nThe downloaded file is available at \(files.temporary.path).")
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let files = downloadTargets.removeValue(forKey: ObjectIdentifier(download)) {
            try? FileManager.default.removeItem(at: files.temporary.deletingLastPathComponent())
            showError("The export did not finish", detail: error.localizedDescription)
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

    private func showError(_ title: String, detail: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail
        alert.beginSheetModal(for: window)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        startupGeneration += 1
        if let server, server.isRunning {
            log("Stopping owned local service PID \(server.processIdentifier).")
            server.terminationHandler = nil
            server.terminate()
            // The backend owns its child jobs. Only this app's exact server PID is touched.
            let deadline = Date().addingTimeInterval(5)
            while server.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.025) }
            if server.isRunning { kill(server.processIdentifier, SIGKILL) }
        }
        try? serverLog?.close()
    }

    @objc private func retryStartup() {
        startupGeneration += 1
        if server?.isRunning == true { server?.terminate() }
        server = nil
        try? serverLog?.close()
        serverLog = nil
        showStatus("Opening your studio", detail: "Starting the local service. Your library stays on this Mac.", failed: false)
        startServer()
    }
    @objc private func openLog() {
        if let logURL { NSWorkspace.shared.open(logURL) }
        else { NSWorkspace.shared.open(dataDirectory) }
    }
    @objc private func openLibrary() {
        try? FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
        NSWorkspace.shared.open(dataDirectory)
    }
    @objc private func openPythonSetup() { NSWorkspace.shared.open(URL(string: "https://www.python.org/downloads/macos/")!) }
    @objc private func reloadStudio() { webView?.reload() }
    @objc private func zoomIn() { if let view = webView { view.pageZoom = min(1.6, view.pageZoom + 0.1) } }
    @objc private func zoomOut() { if let view = webView { view.pageZoom = max(0.7, view.pageZoom - 0.1) } }
    @objc private func resetZoom() { webView?.pageZoom = 1 }
    @objc private func showAbout() {
        NSApplication.shared.orderFrontStandardAboutPanel(options: [
            .applicationName: "YuE Studio",
            .applicationVersion: "1.0",
            .credits: NSAttributedString(string: "A local music workspace for YuE.\nMusic inference requires a separately configured runtime.")
        ])
    }
}

enum StudioError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

let application = NSApplication.shared
let delegate = StudioDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
