import AppKit
import AVFoundation
import Carbon

let API_BASE = "http://127.0.0.1:8756"

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

final class AppDelegate: NSObject, NSApplicationDelegate, NSTextFieldDelegate {
    static var instance: AppDelegate?

    let panel = NSPanel(
        contentRect: NSRect(x: 0, y: 0, width: 440, height: 620),
        styleMask: [.borderless, .nonactivatingPanel],
        backing: .buffered, defer: false)

    let chatStack = NSStackView()
    let scrollView = NSScrollView()
    let inputField = NSTextField()
    let micButton = NSButton()
    let sendButton = NSButton()
    let statusLabel = NSTextField(labelWithString: "")

    var recorder: AVAudioRecorder?
    var recordingURL: URL?
    var pendingApprovalShown = false
    var approvalTimer: Timer?

    var statusItem: NSStatusItem?
    var hotKeyRef: EventHotKeyRef?

    // MARK: - Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppDelegate.instance = self
        setupStatusItem()
        setupPanel()
        installHotKey()
        centerTop()
        startApprovalPolling()
        startSummonPolling()
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let ref = hotKeyRef { UnregisterEventHotKey(ref) }
    }

    // MARK: - Status item

    func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem?.button {
            let img = NSImage(systemSymbolName: "waveform.circle.fill", accessibilityDescription: "Aira")
            img?.isTemplate = true
            button.image = img
            button.target = self
            button.action = #selector(togglePopup)
        }
    }

    // MARK: - Panel

    func setupPanel() {
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.animationBehavior = .utilityWindow

        let effect = NSVisualEffectView()
        effect.material = .hudWindow
        effect.blendingMode = .behindWindow
        effect.state = .active
        effect.wantsLayer = true
        effect.layer?.cornerRadius = 24
        effect.layer?.masksToBounds = true
        effect.translatesAutoresizingMaskIntoConstraints = false
        panel.contentView = effect

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 10
        root.edgeInsets = NSEdgeInsets(top: 14, left: 14, bottom: 14, right: 14)
        root.translatesAutoresizingMaskIntoConstraints = false
        effect.addSubview(root)

        let head = NSStackView()
        head.orientation = .horizontal
        head.alignment = .centerY
        head.spacing = 8

        let dot = NSView()
        dot.wantsLayer = true
        dot.layer?.cornerRadius = 5
        dot.layer?.backgroundColor = NSColor.systemBlue.cgColor
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([dot.widthAnchor.constraint(equalToConstant: 10),
                                     dot.heightAnchor.constraint(equalToConstant: 10)])

        let title = NSTextField(labelWithString: "Aira")
        title.font = NSFont.systemFont(ofSize: 15, weight: .semibold)
        title.textColor = .white

        statusLabel.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        statusLabel.textColor = NSColor(white: 1, alpha: 0.65)
        statusLabel.stringValue = "Option+Space to summon · mic or type"
        statusLabel.lineBreakMode = .byTruncatingTail

        let close = NSButton(title: "", target: self, action: #selector(hidePopup))
        close.bezelStyle = .inline
        close.image = NSImage(systemSymbolName: "xmark", accessibilityDescription: "Close")
        close.imagePosition = .imageOnly
        close.isBordered = false
        close.contentTintColor = NSColor(white: 1, alpha: 0.7)

        head.addArrangedSubview(dot)
        head.addArrangedSubview(title)
        head.addArrangedSubview(statusLabel)
        head.addArrangedSubview(NSView())
        head.addArrangedSubview(close)
        head.setCustomSpacing(6, after: dot)

        chatStack.orientation = .vertical
        chatStack.alignment = .leading
        chatStack.spacing = 8
        chatStack.translatesAutoresizingMaskIntoConstraints = false

        scrollView.documentView = chatStack
        scrollView.hasVerticalScroller = true
        scrollView.drawsBackground = false
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.contentView.postsBoundsChangedNotifications = true

        let inputRow = NSStackView()
        inputRow.orientation = .horizontal
        inputRow.alignment = .centerY
        inputRow.spacing = 8

        micButton.image = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: "Talk")
        micButton.imagePosition = .imageOnly
        micButton.bezelStyle = .texturedRounded
        micButton.target = self
        micButton.action = #selector(micTapped)

        inputField.placeholderString = "Ask Aira anything…"
        inputField.font = NSFont.systemFont(ofSize: 13)
        inputField.isBordered = false
        inputField.wantsLayer = true
        inputField.layer?.cornerRadius = 10
        inputField.layer?.backgroundColor = NSColor(white: 1, alpha: 0.12).cgColor
        inputField.textColor = .white
        inputField.focusRingType = .none
        inputField.delegate = self
        inputField.target = self
        inputField.action = #selector(sendTapped)

        sendButton.image = NSImage(systemSymbolName: "arrow.up.circle.fill", accessibilityDescription: "Send")
        sendButton.imagePosition = .imageOnly
        sendButton.bezelStyle = .texturedRounded
        sendButton.contentTintColor = .systemBlue
        sendButton.target = self
        sendButton.action = #selector(sendTapped)

        inputRow.addArrangedSubview(micButton)
        inputRow.addArrangedSubview(inputField)
        inputRow.addArrangedSubview(sendButton)

        root.addArrangedSubview(head)
        root.addArrangedSubview(scrollView)
        root.addArrangedSubview(inputRow)

        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: effect.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: effect.trailingAnchor),
            root.topAnchor.constraint(equalTo: effect.topAnchor),
            root.bottomAnchor.constraint(equalTo: effect.bottomAnchor),
            head.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -28),
            inputRow.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -28),
            inputField.heightAnchor.constraint(equalToConstant: 30),
            scrollView.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -28),
            chatStack.widthAnchor.constraint(equalTo: scrollView.contentView.widthAnchor),
            dot.widthAnchor.constraint(equalToConstant: 10),
            dot.heightAnchor.constraint(equalToConstant: 10),
            statusLabel.widthAnchor.constraint(greaterThanOrEqualToConstant: 0),
        ])

        addInfoBubble("Aira is ready — press Option+Space or the menu-bar icon to summon. Type or tap the mic to talk.")
    }

    func centerTop() {
        guard let screen = NSScreen.main?.visibleFrame else { return }
        let w = panel.frame.width, h = panel.frame.height
        panel.setFrameOrigin(NSPoint(x: screen.midX - w / 2, y: screen.maxY - h - 28))
    }

    // MARK: - Toggle

    @objc func togglePopup() {
        if panel.isVisible { hidePopup() } else { showPopup() }
    }

    func showPopup() {
        centerTop()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        inputField.becomeFirstResponder()
    }

    @objc func hidePopup() {
        panel.orderOut(nil)
    }

    // MARK: - Chat UI

    func addBubble(_ text: String, isUser: Bool) {
        let label = NSTextField(wrappingLabelWithString: text)
        label.font = NSFont.systemFont(ofSize: 13)
        label.textColor = .white
        label.wantsLayer = true
        label.layer?.cornerRadius = 14
        label.layer?.masksToBounds = true
        label.maximumNumberOfLines = 0
        label.lineBreakMode = .byWordWrapping
        label.preferredMaxLayoutWidth = 300
        let bg = isUser ? NSColor(calibratedRed: 0.31, green: 0.49, blue: 1.0, alpha: 0.9)
                        : NSColor(white: 1, alpha: 0.12)
        label.layer?.backgroundColor = bg.cgColor
        label.translatesAutoresizingMaskIntoConstraints = false
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let row = NSStackView()
        row.orientation = .horizontal
        row.spacing = 0
        row.edgeInsets = NSEdgeInsets(top: 2, left: 0, bottom: 2, right: 0)
        let spacer = NSView()
        if isUser {
            row.alignment = .trailing
            row.addArrangedSubview(NSView())
            row.addArrangedSubview(label)
        } else {
            row.alignment = .leading
            row.addArrangedSubview(label)
            row.addArrangedSubview(NSView())
        }
        row.translatesAutoresizingMaskIntoConstraints = false
        label.setContentHuggingPriority(.defaultLow, for: .horizontal)
        label.setContentHuggingPriority(.required, for: .vertical)
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        row.widthAnchor.constraint(equalToConstant: 412).isActive = true

        chatStack.addArrangedSubview(row)
        scrollToBottom()
    }

    func addInfoBubble(_ text: String) {
        let label = NSTextField(wrappingLabelWithString: text)
        label.font = NSFont.systemFont(ofSize: 12)
        label.textColor = NSColor(white: 1, alpha: 0.8)
        label.alignment = .center
        label.maximumNumberOfLines = 0
        label.preferredMaxLayoutWidth = 380
        label.translatesAutoresizingMaskIntoConstraints = false
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        chatStack.addArrangedSubview(label)
        scrollToBottom()
    }

    func scrollToBottom() {
        chatStack.layoutSubtreeIfNeeded()
        if let doc = scrollView.documentView, doc.isFlipped {
            scrollView.contentView.scroll(to: NSPoint(x: 0, y: doc.frame.maxY))
        } else {
            scrollView.contentView.scrollToEndOfDocument(nil)
        }
        scrollView.reflectScrolledClipView(scrollView.contentView)
    }

    // MARK: - Send

    @objc func sendTapped() {
        let text = inputField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputField.stringValue = ""
        addBubble(text, isUser: true)
        statusLabel.stringValue = "Aira is working…"
        sendToBrain(text)
    }

    func sendToBrain(_ text: String) {
        var req = URLRequest(url: URL(string: "\(API_BASE)/api/chat")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["message": text])
        URLSession.shared.dataTask(with: req) { [weak self] data, _, err in
            DispatchQueue.main.async {
                guard let self = self else { return }
                guard let data = data, err == nil else {
                    self.statusLabel.stringValue = "Aira server not running — start it with `aira --popup`"
                    self.addInfoBubble("Server unreachable. Start it with: ./venv/bin/python -m aira.main --popup")
                    return
                }
                let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                let reply = (json?["reply"] as? String) ?? (json?["error"] as? String) ?? "No reply."
                self.addBubble(reply, isUser: false)
                self.statusLabel.stringValue = "Option+Space to summon · mic or type"
                self.speak(reply)
            }
        }.resume()
    }

    // MARK: - Voice

    @objc func micTapped() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            startStopRecording()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] granted in
                DispatchQueue.main.async {
                    if granted { self?.startStopRecording() }
                    else { self?.statusLabel.stringValue = "Mic access denied — System Settings → Privacy" }
                }
            }
        default:
            statusLabel.stringValue = "Mic access denied — System Settings → Privacy"
        }
    }

    func startStopRecording() {
        if let rec = recorder, rec.isRecording {
            rec.stop()
            return
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("aira_mic.wav")
        recordingURL = url
        try? FileManager.default.removeItem(at: url)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        do {
            let rec = try AVAudioRecorder(url: url, settings: settings)
            recorder = rec
            rec.delegate = self
            rec.record()
            micButton.contentTintColor = .systemRed
            statusLabel.stringValue = "Listening… tap mic to stop"
        } catch {
            statusLabel.stringValue = "Recording failed: \(error.localizedDescription)"
        }
    }

    func sendRecording() {
        guard let url = recordingURL, let data = try? Data(contentsOf: url) else { return }
        micButton.contentTintColor = nil
        statusLabel.stringValue = "Transcribing…"
        var req = URLRequest(url: URL(string: "\(API_BASE)/api/stt")!)
        req.httpMethod = "POST"
        req.setValue("audio/wav", forHTTPHeaderField: "Content-Type")
        req.httpBody = data
        URLSession.shared.dataTask(with: req) { [weak self] data, _, err in
            DispatchQueue.main.async {
                guard let self = self, let data = data, err == nil else {
                    self?.statusLabel.stringValue = "STT failed — is the server running?"
                    return
                }
                let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                let text = (json?["text"] as? String) ?? ""
                let error = (json?["error"] as? String) ?? ""
                if text.isEmpty {
                    self.statusLabel.stringValue = "Didn't catch that\(error.isEmpty ? "" : " — \(error)")"
                    return
                }
                self.statusLabel.stringValue = ""
                self.inputField.stringValue = text
                self.sendTapped()
            }
        }.resume()
    }

    func speak(_ text: String) {
        var req = URLRequest(url: URL(string: "\(API_BASE)/api/tts")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text])
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let path = json["url"] as? String else { return }
            guard let audio = try? Data(contentsOf: URL(string: "\(API_BASE)\(path)")!) else { return }
            let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("aira_reply.mp3")
            try? audio.write(to: tmp)
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
            proc.arguments = [tmp.path]
            try? proc.run()
        }.resume()
    }

    // MARK: - Approvals

    var summonTimer: Timer?

    func startApprovalPolling() {
        approvalTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.pollApprovals()
        }
    }

    func startSummonPolling() {
        summonTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.pollSummon()
        }
    }

    func pollSummon() {
        URLSession.shared.dataTask(with: URL(string: "\(API_BASE)/api/summon")!) { [weak self] data, _, _ in
            guard let self = self, let data = data else { return }
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            DispatchQueue.main.async {
                if json?["summon"] as? Bool == true {
                    self.showPopup()
                }
            }
        }.resume()
    }

    func pollApprovals() {
        guard panel.isVisible else { return }
        URLSession.shared.dataTask(with: URL(string: "\(API_BASE)/api/pending")!) { [weak self] data, _, _ in
            guard let self = self, let data = data else { return }
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let question = json?["question"] as? String
            DispatchQueue.main.async {
                if let q = question, !q.isEmpty {
                    if !self.pendingApprovalShown {
                        self.pendingApprovalShown = true
                        self.addApprovalBubble(q)
                    }
                } else {
                    self.pendingApprovalShown = false
                }
            }
        }.resume()
    }

    func addApprovalBubble(_ question: String) {
        let label = NSTextField(wrappingLabelWithString: "Aira needs approval: \(question)")
        label.font = NSFont.systemFont(ofSize: 13)
        label.textColor = .white
        label.maximumNumberOfLines = 0
        label.preferredMaxLayoutWidth = 300
        label.wantsLayer = true
        label.layer?.cornerRadius = 14
        label.layer?.masksToBounds = true
        label.layer?.backgroundColor = NSColor(calibratedRed: 0.85, green: 0.6, blue: 0.2, alpha: 0.35).cgColor

        let approveBtn = NSButton(title: "Approve", target: self, action: #selector(approveAction(_:)))
        approveBtn.bezelStyle = .rounded
        approveBtn.tag = 1
        let denyBtn = NSButton(title: "Deny", target: self, action: #selector(approveAction(_:)))
        denyBtn.bezelStyle = .rounded
        denyBtn.tag = 0

        let row = NSStackView()
        row.orientation = .vertical
        row.alignment = .leading
        row.spacing = 8
        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 8
        buttons.addArrangedSubview(approveBtn)
        buttons.addArrangedSubview(denyBtn)
        row.addArrangedSubview(label)
        row.addArrangedSubview(buttons)
        row.translatesAutoresizingMaskIntoConstraints = false
        chatStack.addArrangedSubview(row)
        scrollToBottom()
    }

    @objc func approveAction(_ sender: NSButton) {
        let approved = sender.tag == 1
        var req = URLRequest(url: URL(string: "\(API_BASE)/api/pending")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["approve": approved])
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.pendingApprovalShown = false }
        }.resume()
    }
}

extension AppDelegate: AVAudioRecorderDelegate {
    func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        if flag { sendRecording() }
    }
}

// MARK: - Hotkey (Option+Space)

private let hotKeyHandler: @convention(c) (EventHandlerCallRef?, EventRef?, UnsafeMutableRawPointer?) -> OSStatus = { _, _, _ in
    DispatchQueue.main.async { AppDelegate.instance?.togglePopup() }
    return noErr
}

extension AppDelegate {
    func installHotKey() {
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), hotKeyHandler, 1, &eventType, nil, nil)
        var hotKeyID = EventHotKeyID(signature: OSType(0x52415331), id: 1)
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(optionKey), hotKeyID, GetApplicationEventTarget(), 0, &hotKeyRef)
    }
}

let delegate = AppDelegate()
app.delegate = delegate
app.run()
