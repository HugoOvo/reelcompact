import AppKit
import Foundation
import SwiftUI

struct RunnerEvent: Decodable {
    let type: String
    let percent: Double?
    let phase: String?
    let message: String?
    let input: String?
    let output: String?
    let size: Int?
    let completed: Int?
    let failures: Int?
}

final class CompressionRunner: ObservableObject {
    @Published var progress: Double = 0
    @Published var phase: String = "准备压缩"
    @Published var currentFile: String = ""
    @Published var logs: [String] = []
    @Published var errors: [String] = []
    @Published var isRunning = false
    @Published var isCancelling = false
    @Published var outputs: [String] = []

    let codec: String
    let files: [String]
    private var process: Process?
    private var stdoutBuffer = Data()
    private var stderrBuffer = Data()
    private var hasStarted = false
    private var wasCancelled = false

    init(codec: String, files: [String]) {
        self.codec = codec
        self.files = files
        self.currentFile = files.first ?? ""
    }

    func start() {
        guard !hasStarted, !files.isEmpty else { return }
        hasStarted = true
        isRunning = true
        progress = 0
        phase = "启动压缩器"
        logs.append("开始处理 \(files.count) 个文件")

        guard let core = Bundle.main.resourceURL?.appendingPathComponent("shrink_core.py"),
              FileManager.default.fileExists(atPath: core.path) else {
            fail("应用资源中缺少 shrink_core.py")
            return
        }

        let process = Process()
        let stdout = Pipe()
        let stderr = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [core.path, "--codec", codec] + files
        process.standardOutput = stdout
        process.standardError = stderr
        self.process = process

        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async {
                self?.consumeStdout(data)
            }
        }
        stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async {
                self?.consumeStderr(data)
            }
        }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                self?.finish(returnCode: process.terminationStatus)
            }
        }

        do {
            try process.run()
        } catch {
            fail("无法启动压缩器：\(error.localizedDescription)")
        }
    }

    func cancel() {
        guard let process, process.isRunning else { return }
        isCancelling = true
        wasCancelled = true
        phase = "正在取消"
        process.terminate()
    }

    private func consumeStdout(_ data: Data) {
        stdoutBuffer.append(data)
        while let newline = stdoutBuffer.firstIndex(of: 0x0A) {
            let lineData = stdoutBuffer[..<newline]
            stdoutBuffer.removeSubrange(...newline)
            guard let line = String(data: lineData, encoding: .utf8), !line.isEmpty else { continue }
            handleJSONLine(line)
        }
    }

    private func consumeStderr(_ data: Data) {
        stderrBuffer.append(data)
        guard stderrBuffer.count < 16_384 else {
            stderrBuffer.removeFirst(stderrBuffer.count - 12_000)
            return
        }
    }

    private func handleJSONLine(_ line: String) {
        guard let data = line.data(using: .utf8),
              let event = try? JSONDecoder().decode(RunnerEvent.self, from: data) else {
            return
        }
        switch event.type {
        case "progress":
            if let percent = event.percent {
                progress = max(progress, min(1, percent / 100))
            }
            if let phase = event.phase { self.phase = phase }
        case "file_start":
            currentFile = URL(fileURLWithPath: event.input ?? "").lastPathComponent
            logs.append("开始：\(currentFile)")
        case "log":
            if let message = event.message { logs.append(message) }
        case "skipped":
            if let name = event.input.map({ URL(fileURLWithPath: $0).lastPathComponent }) {
                logs.append("已跳过（符合体积要求）：\(name)")
            }
        case "done":
            if let output = event.output {
                outputs.append(output)
                let name = URL(fileURLWithPath: output).lastPathComponent
                let size = event.size.map { String(format: "%.2f MiB", Double($0) / 1_048_576) } ?? ""
                logs.append("完成：\(name) \(size)")
            }
        case "file_error":
            let name = event.input.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "文件"
            errors.append("\(name)：\(event.message ?? "未知错误")")
        case "cancelled":
            phase = "已取消"
        case "summary":
            if let failures = event.failures, failures == 0 {
                phase = "全部完成"
                progress = 1
                notifySuccess()
                revealFirstOutput()
            }
        default:
            break
        }
    }

    private func finish(returnCode: Int32) {
        process = nil
        isRunning = false
        isCancelling = false
        if wasCancelled {
            phase = "已取消"
            logs.append("已取消；未完成的临时文件已清理")
            return
        }
        if returnCode != 0 && errors.isEmpty {
            let detail = String(data: stderrBuffer, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            errors.append(detail?.isEmpty == false ? detail! : "压缩器退出码 \(returnCode)")
        }
        if !errors.isEmpty { phase = "有文件失败" }
    }

    private func fail(_ message: String) {
        isRunning = false
        phase = "失败"
        errors.append(message)
    }

    private func revealFirstOutput() {
        guard let first = outputs.first else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: first)])
    }

    private func notifySuccess() {
        let count = outputs.count
        let message: String
        if count == 0 {
            message = "视频已符合 20 MB 要求"
        } else if count == 1 {
            message = "视频已压缩完成"
        } else {
            message = "\(count) 个视频已压缩完成"
        }
        let escaped = message
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", "display notification \"\(escaped)\" with title \"轻帧 ReelCompact\""]
        try? process.run()
    }
}

struct ContentView: View {
    @ObservedObject var runner: CompressionRunner
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("轻帧 ReelCompact")
                        .font(.title2.weight(.semibold))
                    Text(runner.codec == "h265" ? "H.265 高画质模式" : "H.264 兼容模式")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(String(format: "%.0f%%", runner.progress * 100))
                    .font(.system(.title3, design: .rounded, weight: .semibold))
                    .monospacedDigit()
            }

            VStack(alignment: .leading, spacing: 7) {
                Text(runner.currentFile)
                    .font(.headline)
                    .lineLimit(1)
                    .truncationMode(.middle)
                ProgressView(value: runner.progress)
                Text(runner.phase)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(runner.logs.enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(10)
            }
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.2)))

            HStack {
                Spacer()
                if runner.isRunning {
                    Button(runner.isCancelling ? "正在取消…" : "取消") {
                        runner.cancel()
                    }
                    .keyboardShortcut(.cancelAction)
                    .disabled(runner.isCancelling)
                } else {
                    Button("关闭") { NSApp.terminate(nil) }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(22)
        .frame(minWidth: 560, minHeight: 390)
        .onAppear { runner.start() }
        .alert("压缩失败", isPresented: Binding(
            get: { !runner.errors.isEmpty && !runner.isRunning },
            set: { _ in }
        )) {
            Button("知道了") { NSApp.terminate(nil) }
        } message: {
            Text(runner.errors.joined(separator: "\n\n"))
        }
    }
}


final class SetupModel: ObservableObject {
    @Published var message = "正在准备 Finder 快速操作…"
    @Published var isInstalling = true
    @Published var needsMove = false
    private var hasStarted = false

    var installedPathIsValid: Bool {
        let path = Bundle.main.bundlePath
        let homeApps = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications").path
        return path == "/Applications/ReelCompact.app" || path.hasPrefix(homeApps + "/")
    }

    func installQuickActions() {
        guard !hasStarted else { return }
        hasStarted = true
        guard installedPathIsValid else {
            isInstalling = false
            needsMove = true
            message = "请先把 App 拖到“应用程序”文件夹，然后再打开"
            return
        }
        guard let script = Bundle.main.resourceURL?.appendingPathComponent("make_workflows.py") else {
            isInstalling = false
            message = "安装资源不完整，请重新安装 App"
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            process.arguments = [script.path]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                process.waitUntilExit()
                let update = Process()
                update.executableURL = URL(fileURLWithPath: "/System/Library/CoreServices/pbs")
                update.arguments = ["-update"]
                try? update.run()
                update.waitUntilExit()
                DispatchQueue.main.async {
                    self.isInstalling = false
                    if process.terminationStatus == 0 {
                        self.message = "Finder 快速操作已经安装；如有需要，请在系统设置中打开开关"
                    } else {
                        self.message = "快速操作安装失败，请重新打开 App 再试"
                    }
                }
            } catch {
                DispatchQueue.main.async {
                    self.isInstalling = false
                    self.message = "快速操作安装失败：\(error.localizedDescription)"
                }
            }
        }
    }

    func openQuickActionSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.ExtensionsPreferences?extensionPointIdentifier=com.apple.finder-quick-actions") {
            NSWorkspace.shared.open(url)
        }
    }
}

struct SetupView: View {
    @ObservedObject private var model = SetupModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 14) {
                Image(systemName: "film.stack")
                    .font(.system(size: 38, weight: .medium))
                    .foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 3) {
                    Text("轻帧 ReelCompact").font(.title2.weight(.semibold))
                    Text("Finder 右键快速压缩到 19.5 MiB 以下").foregroundStyle(.secondary)
                }
            }

            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    Label(model.message, systemImage: model.needsMove ? "arrow.down.app" : (model.isInstalling ? "gearshape.2" : "checkmark.circle"))
                    Text("首次启用需要到“系统设置 → 访达”打开两个“压缩到20MB”开关，只需操作一次。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
            }

            HStack {
                Button("打开访达快速操作设置") { model.openQuickActionSettings() }
                    .disabled(model.isInstalling || model.needsMove)
                Button("打开应用程序文件夹") {
                    NSWorkspace.shared.open(FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications"))
                }
                Spacer()
                Button("关闭") { NSApp.terminate(nil) }
            }
        }
        .padding(24)
        .frame(width: 560)
        .onAppear { model.installQuickActions() }
    }
}

@main
struct ReelCompactApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    private let runner: CompressionRunner

    init() {
        let parsed = Self.parseArguments(CommandLine.arguments)
        runner = CompressionRunner(codec: parsed.codec, files: parsed.files)
    }

    var body: some Scene {
        WindowGroup {
            if runner.files.isEmpty {
                SetupView()
            } else {
                ContentView(runner: runner)
            }
        }
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }

    private static func parseArguments(_ arguments: [String]) -> (codec: String, files: [String]) {
        var codec = "h264"
        var files: [String] = []
        var expectCodec = false
        for argument in arguments.dropFirst() {
            if argument == "--" { continue }
            if expectCodec {
                codec = argument == "h265" ? "h265" : "h264"
                expectCodec = false
            } else if argument == "--codec" {
                expectCodec = true
            } else if !argument.hasPrefix("-psn_") {
                files.append(argument)
            }
        }
        return (codec, files)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.activate(ignoringOtherApps: true)
    }
}
