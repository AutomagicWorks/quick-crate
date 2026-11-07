import SwiftUI
import AppKit
import UserNotifications

/// Where to look for yt-dlp / ffmpeg / ffprobe. Apps opened from Finder get a minimal PATH,
/// so the usual install folders are checked first, then whatever PATH the app was given.
let searchDirs: [String] = {
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    var dirs = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"]
    for d in (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        where !dirs.contains(d) { dirs.append(d) }
    return dirs
}()

/// Full path to a command-line tool, or nil if it isn't installed.
func findTool(_ name: String) -> String? {
    searchDirs.map { "\($0)/\(name)" }.first { FileManager.default.isExecutableFile(atPath: $0) }
}
func bin(_ name: String) -> String { findTool(name) ?? name }
let installHint = "Install it first: run  brew install yt-dlp ffmpeg  in Terminal (see the README)."

let downloadsDir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
let mp3Rates: [Double] = [8, 16, 24, 32, 40, 48, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
let linkPattern = #"^https?://\S+$"#
/// Crops the (usually 16:9) video thumbnail to a centred square before it is embedded.
let squareCropArgs = "ThumbnailsConvertor:-vf crop=\"'min(iw,ih)':'min(iw,ih)'\""
/// "Artist - Title (Official Video)" -> artist and title tags, and a clean "Artist - Title.ext" filename.
/// Mix names such as "(Extended Mix)" are kept; only video-ish suffixes are removed.
let tagArgs = ["--parse-metadata", "%(title)s:%(meta_title)s",
               "--parse-metadata", "title:(?P<meta_artist>.+?) - (?P<meta_title>.+)",
               "--replace-in-metadata", "meta_title",
               #"(?i)\s*[(\[][^)\]]*\b(official|lyrics?|audio|video|visuali[sz]er|hd|4k|mv)\b[^)\]]*[)\]]"#, ""]
/// Cuts sections SponsorBlock users marked as non-music (talking intros/outros) out of music videos. YouTube only.
let sponsorBlockArgs = ["--sponsorblock-remove", "music_offtopic"]
let ytdlpOldDays = 60
/// Shown next to the title, so bug reports can say which version they are on (set from VERSION by build.sh).
let appVersion = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev"
/// Quotes a value for yt-dlp options that it splits like a Unix shell (such as --postprocessor-args).
func shellQuote(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }
let outputName = "%(meta_artist,artist&{} - |)s%(meta_title,title)s.%(ext)s"

var childEnv: [String: String] {
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = searchDirs.joined(separator: ":")
    return env
}

/// Runs a tool to completion and returns its stdout.
func capture(_ exe: String, _ args: [String]) -> Data {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    p.environment = childEnv
    p.qualityOfService = .background  // never compete with DJ software for CPU or disk
    let out = Pipe()
    p.standardOutput = out
    p.standardError = FileHandle.nullDevice
    guard (try? p.run()) != nil else { return Data() }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return data
}

/// Runs a tool to completion and returns its exit status and combined output.
func runTool(_ exe: String, _ args: [String]) -> (status: Int32, output: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    p.environment = childEnv
    let out = Pipe()
    p.standardOutput = out
    p.standardError = out
    guard (try? p.run()) != nil else { return (-1, "Couldn't run \(exe)") }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

/// Installed yt-dlp version and its age in days (yt-dlp versions are release dates, e.g. 2026.10.26).
func ytdlpVersion() -> (version: String, ageDays: Int?)? {
    guard let path = findTool("yt-dlp") else { return nil }
    let v = String(decoding: capture(path, ["--version"]), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
    let parts = v.split(separator: ".").prefix(3).compactMap { Int($0) }
    guard parts.count == 3,
          let released = Calendar.current.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])) else { return (v, nil) }
    return (v, Calendar.current.dateComponents([.day], from: released, to: Date()).day)
}

/// Updates yt-dlp the way it was installed: Homebrew if it came from there, otherwise yt-dlp -U.
func updateYtdlp() -> (ok: Bool, message: String) {
    guard let path = findTool("yt-dlp") else { return (false, "yt-dlp wasn't found. " + installHint) }
    let before = ytdlpVersion()?.version ?? ""
    let real = (path as NSString).resolvingSymlinksInPath
    let result: (status: Int32, output: String)
    if let brew = findTool("brew"), real.contains("/Cellar/") || real.hasPrefix("/opt/homebrew/") {
        result = runTool(brew, ["upgrade", "yt-dlp"])
    } else {
        result = runTool(path, ["-U"])
    }
    let after = ytdlpVersion()?.version ?? before
    if after != before { return (true, "yt-dlp updated from \(before) to \(after).") }
    if result.status == 0 { return (true, "yt-dlp \(after) is already the latest version.") }
    let hint = result.output.split(separator: "\n").last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) ?? "unknown error"
    return (false, "Couldn't update yt-dlp: \(hint)")
}

enum Stage { case idle, prep, download, convert, finish, done, failed, cancelled }

enum AudioFormat: String, CaseIterable, Identifiable {
    case mp3, m4a, original
    var id: String { rawValue }
    var label: String {
        switch self {
        case .mp3: return "MP3"
        case .m4a: return "M4A (original AAC)"
        case .original: return "Original (best stream)"
        }
    }
    var help: String {
        switch self {
        case .mp3: return "Converted to MP3. Works in every DJ app and on CDJs; the safest choice."
        case .m4a: return "Saves the site's AAC audio as-is, with no conversion. Works in Rekordbox, Serato, Traktor and Apple Music."
        case .original: return "Saves the best audio stream as-is, with no conversion. Usually Opus, which Rekordbox, Serato, Traktor and Apple Music can't play."
        }
    }
    var converts: Bool { self == .mp3 }
}

struct QualityInfo {
    var summary: String
    var note: String
}

@MainActor
final class Downloader: ObservableObject {
    @Published var url = ""
    @Published var vbr = UserDefaults.standard.bool(forKey: "vbr") { didSet { UserDefaults.standard.set(vbr, forKey: "vbr") } }
    @Published var format = AudioFormat(rawValue: UserDefaults.standard.string(forKey: "format") ?? "") ?? .mp3 {
        didSet { UserDefaults.standard.set(format.rawValue, forKey: "format") }
    }
    @Published var squareArt = UserDefaults.standard.object(forKey: "squareArt") as? Bool ?? true {
        didSet { UserDefaults.standard.set(squareArt, forKey: "squareArt") }
    }
    @Published var removeNonMusic = UserDefaults.standard.bool(forKey: "removeNonMusic") {
        didSet { UserDefaults.standard.set(removeNonMusic, forKey: "removeNonMusic") }
    }
    @Published var oldYtdlpNotice: String?
    @Published var updating = false
    @Published var updateStatus: String?
    @Published var stage: Stage = .idle
    @Published var percent = 0.0
    @Published var cpercent = 0.0
    @Published var title = ""
    @Published var errorText = ""
    @Published var filePath: String?
    @Published var quality: QualityInfo?
    @Published var art: NSImage?
    @Published var showAdvanced = false
    @Published var clipboardHasText = false
    @Published var downloadDir: URL = {
        if let p = UserDefaults.standard.string(forKey: "downloadDir"), FileManager.default.fileExists(atPath: p) {
            return URL(fileURLWithPath: p)
        }
        return downloadsDir
    }()
    var duration = 0.0
    var runningFormat: AudioFormat = .mp3
    @Published var cancelRequested = false
    var runningPid: Int32 = 0
    private var askedForNotifications = false

    var busy: Bool { [.prep, .download, .convert, .finish].contains(stage) }

    var fraction: Double? {
        switch stage {
        case .download: return percent / 200
        case .convert: return 0.5 + cpercent / 100 * 0.45
        case .done: return 1
        default: return nil
        }
    }

    var finished: Bool { stage == .done && url.trimmingCharacters(in: .whitespaces).isEmpty }

    var buttonTitle: String {
        if busy { return title.isEmpty ? "Downloading…" : "Downloading " + title }
        if finished { return "Finished!" }
        return "Download audio"
    }

    var message: String {
        let t = title.isEmpty ? "" : title + " — "
        switch stage {
        case .idle: return ""
        case .prep: return "Analyzing video and preparing..."
        case .download: return t + "Downloading \(Int(percent))%"
        case .convert: return t + (runningFormat.converts ? "Converting to MP3 \(Int(cpercent))%" : "Saving original audio…")
        case .finish: return t + "Embedding cover art and tags…"
        case .done: return "Saved: " + ((filePath as NSString?)?.lastPathComponent ?? "")
        case .failed: return errorText
        case .cancelled: return "Download cancelled."
        }
    }

    /// Checks whether the clipboard holds text, without reading it (reading would trigger
    /// macOS's paste-privacy prompt; the Paste & download button reads it on click instead).
    func refreshClipboard() {
        let types = NSPasteboard.general.types ?? []
        clipboardHasText = types.contains(.string) || types.contains(.URL)
    }

    func pasteAndDownload() {
        let s = NSPasteboard.general.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        url = s
        start()
    }

    func dropped(_ links: [URL]) -> Bool {
        guard !busy, let u = links.first(where: { ["http", "https"].contains($0.scheme?.lowercased() ?? "") }) else { return false }
        url = u.absoluteString
        start()
        return true
    }

    func start() {
        let link = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard link.range(of: linkPattern, options: .regularExpression) != nil else {
            stage = .failed
            errorText = "Please paste a full link starting with http:// or https://"
            return
        }
        let missing = ["yt-dlp", "ffmpeg"].filter { findTool($0) == nil }
        guard missing.isEmpty else {
            stage = .failed
            errorText = missing.joined(separator: " and ") + " wasn't found. " + installHint
            return
        }
        guard FileManager.default.fileExists(atPath: downloadDir.path) else {
            stage = .failed
            errorText = "The download folder " + (downloadDir.path as NSString).abbreviatingWithTildeInPath
                + " no longer exists. Choose another one under advanced options."
            return
        }
        if !askedForNotifications {
            askedForNotifications = true
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        }
        percent = 0; cpercent = 0; title = ""; duration = 0
        filePath = nil; quality = nil; art = nil; errorText = ""; updateStatus = nil
        cancelRequested = false; runningPid = 0
        stage = .prep
        runningFormat = format
        let fmt = format, useVBR = vbr, square = squareArt, sponsor = removeNonMusic, dir = downloadDir
        Task.detached { await self.run(link, fmt, useVBR, square, sponsor, dir) }
    }

    /// Stops the download. yt-dlp handles SIGINT by stopping its ffmpeg child; SIGTERM follows if it hangs.
    func cancel() {
        guard busy else { return }
        cancelRequested = true
        errorText = ""
        let pid = runningPid
        guard pid > 0 else { return }
        kill(pid, SIGINT)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { if kill(pid, 0) == 0 { kill(pid, SIGTERM) } }
    }

    /// Stops a running download when the app quits (Quit button, Cmd+Q or closing the window), so yt-dlp
    /// and ffmpeg don't keep running in the background. yt-dlp stops its ffmpeg child on SIGINT.
    func stopForQuit() {
        if runningPid > 0 { kill(runningPid, SIGINT) }
    }

    func quitApp() {
        if busy {
            let alert = NSAlert()
            alert.messageText = "A download is still running."
            alert.informativeText = "Cancel it and quit Quick Crate?"
            alert.addButton(withTitle: "Cancel Download and Quit")
            alert.addButton(withTitle: "Keep Downloading")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
        }
        NSApp.terminate(nil)
    }

    func checkYtdlpAge() {
        Task.detached {
            let info = ytdlpVersion()
            await MainActor.run {
                if let info, let age = info.ageDays, age > ytdlpOldDays {
                    self.oldYtdlpNotice = "Your yt-dlp (\(info.version)) is \(age) days old. Sites change often, and updating fixes most download errors."
                } else {
                    self.oldYtdlpNotice = nil
                }
            }
        }
    }

    func runUpdate() {
        updating = true
        updateStatus = "Updating yt-dlp…"
        Task.detached {
            let r = updateYtdlp()
            await MainActor.run {
                self.updating = false
                self.updateStatus = r.message
                if r.ok { self.oldYtdlpNotice = nil }
            }
        }
    }

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Choose"
        panel.message = "Choose where downloads are saved"
        panel.directoryURL = downloadDir
        if panel.runModal() == .OK, let u = panel.url {
            downloadDir = u
            UserDefaults.standard.set(u.path, forKey: "downloadDir")
        }
    }

    func openFile() { if let f = filePath { NSWorkspace.shared.open(URL(fileURLWithPath: f)) } }
    func showInFolder() {
        if let f = filePath { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: f)]) }
    }

    /// Posts a notification when the window isn't in front. Clicking it shows the file.
    func notify(_ heading: String, _ body: String, path: String? = nil) {
        guard !NSApp.isActive else { return }
        let c = UNMutableNotificationContent()
        c.title = heading
        c.body = body
        c.sound = .default
        if let p = path { c.userInfo = ["path": p] }
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }

    nonisolated func cbrRate(_ url: String) -> Int {
        let out = String(decoding: capture(bin("yt-dlp"), ["-f", "bestaudio", "--no-playlist", "--print", "%(abr)s", "--", url]), as: UTF8.self)
        guard let last = out.split(separator: "\n").last, let abr = Double(last.trimmingCharacters(in: .whitespaces)) else { return 320 }
        return Int(mp3Rates.first { $0 >= abr - 1 } ?? 320)
    }

    nonisolated func formatArgs(_ fmt: AudioFormat, _ vbr: Bool, _ link: String) -> [String] {
        switch fmt {
        case .mp3:
            return ["-f", "bestaudio", "-x", "--audio-format", "mp3", "--audio-quality", vbr ? "0" : "\(cbrRate(link))K"]
        case .m4a:
            // Prefer the AAC stream so it is copied as-is; only converts if a site has no AAC.
            return ["-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a"]
        case .original:
            return ["-f", "bestaudio", "-x", "--audio-format", "best"]
        }
    }

    nonisolated func run(_ link: String, _ fmt: AudioFormat, _ useVBR: Bool, _ square: Bool, _ sponsor: Bool, _ dir: URL) async {
        // Intermediate files live in their own temp folder, so a cancelled download leaves nothing behind.
        let tmp = NSTemporaryDirectory() + "quick-crate-\(UUID().uuidString)"
        try? FileManager.default.createDirectory(atPath: tmp, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: tmp) }
        let pfile = tmp + "/convert.progress"
        var args = formatArgs(fmt, useVBR, link)
        args += ["--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg"] + tagArgs
        if square { args += ["--ppa", squareCropArgs] }
        if sponsor { args += sponsorBlockArgs }
        args += ["--no-playlist", "--newline", "--progress", "--ffmpeg-location", (bin("ffmpeg") as NSString).deletingLastPathComponent,
                 "--progress-template", "download:PROG %(progress._percent_str)s",
                 "--progress-template", "postprocess:PP %(progress.postprocessor)s|%(progress.status)s",
                 "--print", "pre_process:TITLE %(title)s",
                 "--print", "before_dl:SRC %(acodec)s|%(abr)s",
                 "--print", "before_dl:DUR %(duration)s",
                 "--postprocessor-args", "ExtractAudio:-progress \(shellQuote(pfile)) -nostats",
                 "--print", "after_move:FILE %(filepath)s",
                 "-o", outputName, "-P", dir.path, "-P", "temp:\(tmp)", "--", link]
        let p = Process()
        p.executableURL = URL(fileURLWithPath: bin("yt-dlp"))
        p.arguments = args
        p.environment = childEnv
        // Background priority (CPU and disk), inherited by ffmpeg, so a download or conversion
        // never causes audio dropouts in DJ software running on the same Mac.
        p.qualityOfService = .background
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        if await MainActor.run(body: { self.cancelRequested }) {
            await MainActor.run { self.stage = .cancelled }
            return
        }
        do { try p.run() } catch {
            let msg = error.localizedDescription
            await MainActor.run { self.stage = .failed; self.errorText = msg }
            return
        }
        let pid = p.processIdentifier
        await MainActor.run { self.runningPid = pid }
        let poll = Task { @MainActor in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 300_000_000)
                guard self.stage == .convert, self.duration > 0,
                      let txt = try? String(contentsOfFile: pfile, encoding: .utf8),
                      let l = txt.split(separator: "\n").last(where: { $0.hasPrefix("out_time_us=") }),
                      let us = Double(l.dropFirst(12)) else { continue }
                self.cpercent = max(self.cpercent, min(99, us / 1e6 / self.duration * 100))
            }
        }
        var src = "", file: String?, tail: [String] = []
        do {
            for try await line in pipe.fileHandleForReading.bytes.lines {
                if line.hasPrefix("PROG ") {
                    if let m = line.range(of: #"[\d.]+(?=%)"#, options: .regularExpression), let v = Double(line[m]) {
                        await MainActor.run { if self.stage == .prep || self.stage == .download { self.stage = .download; self.percent = v } }
                    }
                } else if line.hasPrefix("TITLE ") {
                    let t = String(line.dropFirst(6)); await MainActor.run { self.title = t }
                } else if line.hasPrefix("SRC ") {
                    src = String(line.dropFirst(4))
                } else if line.hasPrefix("DUR ") {
                    if let d = Double(line.dropFirst(4)) { await MainActor.run { self.duration = d } }
                } else if line.hasPrefix("PP ") {
                    if line == "PP ExtractAudio|started" { await MainActor.run { self.stage = .convert } }
                    else if line == "PP ExtractAudio|finished" || line == "PP Metadata|started" { await MainActor.run { self.stage = .finish } }
                } else if line.hasPrefix("FILE ") {
                    file = String(line.dropFirst(5))
                } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                    tail.append(line)
                }
            }
        } catch {}
        p.waitUntilExit()
        poll.cancel()
        await MainActor.run { self.runningPid = 0 }
        if await MainActor.run(body: { self.cancelRequested }) {
            // Finished just as Cancel was pressed: honour the cancel.
            if let f = file { try? FileManager.default.removeItem(atPath: f) }
            await MainActor.run { self.stage = .cancelled }
            return
        }
        if p.terminationStatus == 0, let f = file, FileManager.default.fileExists(atPath: f) {
            let q = describeQuality(f, src, fmt, useVBR)
            let img = NSImage(data: capture(bin("ffmpeg"), ["-v", "error", "-i", f, "-an", "-frames:v", "1", "-c:v", "copy", "-f", "image2pipe", "-"]))
            await MainActor.run {
                self.filePath = f; self.quality = q; self.art = img
                self.cpercent = 100; self.stage = .done; self.url = ""
                self.notify("Download finished", (f as NSString).lastPathComponent, path: f)
            }
        } else {
            let errs = tail.filter { $0.contains("ERROR") }
            var msg = (errs.last ?? tail.last) ?? "Download failed"
            if msg.hasPrefix("ERROR:") { msg = String(msg.dropFirst(6)).trimmingCharacters(in: .whitespaces) }
            let finalMsg = msg
            await MainActor.run {
                self.errorText = finalMsg; self.stage = .failed
                self.notify("Download failed", finalMsg)
            }
        }
    }

    nonisolated func describeQuality(_ path: String, _ src: String, _ fmt: AudioFormat, _ vbr: Bool) -> QualityInfo {
        // What came in: the source stream yt-dlp picked.
        let parts = src.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        var srcCodec = parts.first ?? ""
        var srcAbr = parts.count > 1 ? parts[1] : ""
        if ["NA", "None"].contains(srcCodec) { srcCodec = "" }
        if ["NA", "None"].contains(srcAbr) { srcAbr = "" }
        let names = [("opus", "Opus"), ("mp4a", "AAC"), ("aac", "AAC"), ("vorbis", "Vorbis"), ("mp3", "MP3")]
        func nice(_ c: String) -> String { names.first { c.hasPrefix($0.0) }?.1 ?? (c.isEmpty ? "original" : c) }
        let srcName = nice(srcCodec)
        let origin = Double(srcAbr).map { "\(srcName) source (~\(Int($0.rounded())) kbps)" } ?? "\(srcName) source"

        // What came out: probe the saved file.
        var outCodec = fmt == .mp3 ? "mp3" : ""
        var summary = fmt == .mp3 ? (vbr ? "MP3, highest VBR setting" : "MP3, constant bitrate") : "Original audio"
        let data = capture(bin("ffprobe"), ["-v", "error", "-select_streams", "a:0",
                                            "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=bit_rate", "-of", "json", path])
        if let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let st = (j["streams"] as? [[String: Any]])?.first {
            outCodec = st["codec_name"] as? String ?? outCodec
            let fmtInfo = j["format"] as? [String: Any]
            let br = (st["bit_rate"] as? String).flatMap { Double($0) } ?? (fmtInfo?["bit_rate"] as? String).flatMap { Double($0) }
            let sr = (st["sample_rate"] as? String).flatMap { Double($0) }
            let ch = st["channels"] as? Int ?? 2
            let chn = ch == 1 ? "mono" : ch == 2 ? "stereo" : "multichannel"
            let ext = (path as NSString).pathExtension.uppercased()
            let head: String
            if fmt == .mp3 {
                head = "MP3"
            } else {
                head = ext == nice(outCodec).uppercased() ? nice(outCodec) : "\(ext) (\(nice(outCodec)))"
            }
            var bits = [head]
            if let br {
                bits.append("~\(Int((br / 1000).rounded())) kbps" + (fmt == .mp3 ? (vbr ? " VBR (highest setting)" : " CBR (constant)") : ""))
            }
            if let sr { bits.append("\((sr / 1000).formatted()) kHz") }
            bits.append(chn)
            summary = bits.joined(separator: ", ")
        }

        let copied = fmt != .mp3 && !srcCodec.isEmpty && nice(srcCodec) == nice(outCodec)
        var note: String
        if copied {
            note = "This is the site's \(srcName) audio saved exactly as streamed, with no conversion, so no quality was lost."
        } else {
            note = "Converted from the best available \(origin). It was already lossy, so this file can't sound better than the source, but it keeps nearly all of it."
        }
        if outCodec == "opus" { note += " Note: Rekordbox, Serato, Traktor and Apple Music can't play Opus. Choose MP3 or M4A for DJ use." }
        return QualityInfo(summary: summary, note: note)
    }
}

struct ContentView: View {
    @StateObject private var d = Downloader()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(nsImage: NSApplication.shared.applicationIconImage).resizable().frame(width: 48, height: 48)
                Text("Quick Crate").font(.title2.bold())
                Text("v\(appVersion)").font(.callout).foregroundStyle(.secondary)
                Spacer()
                Button("Quit") { d.quitApp() }.controlSize(.small).help("Quit Quick Crate")
            }
            Text("Built by a DJ, for DJs. Paste or drop a link (YouTube or any site yt-dlp supports) to add its audio to your crate in seconds.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let notice = d.oldYtdlpNotice {
                VStack(alignment: .leading, spacing: 6) {
                    Text(notice).font(.callout).fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 8) {
                        Button("Update yt-dlp") { d.runUpdate() }.disabled(d.updating || d.busy)
                        if d.updating { ProgressView().controlSize(.small) }
                    }
                }
                .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.orange.opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
            }
            if let status = d.updateStatus {
                Text(status).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TextField("https://www.youtube.com/watch?v=...", text: $d.url)
                .textFieldStyle(.roundedBorder).controlSize(.large)
                .disabled(d.busy).onSubmit { if !d.busy { d.start() } }
            Button { withAnimation(.easeInOut(duration: 0.15)) { d.showAdvanced.toggle() } } label: {
                Label(d.showAdvanced ? "Hide advanced options" : "Show advanced options",
                      systemImage: d.showAdvanced ? "chevron.down" : "chevron.right")
                .contentShape(Rectangle())
            }.buttonStyle(.plain).foregroundStyle(.secondary)
            if d.showAdvanced {
                VStack(alignment: .leading, spacing: 10) {
                    Picker("Format:", selection: $d.format) {
                        ForEach(AudioFormat.allCases) { Text($0.label).tag($0) }
                    }.pickerStyle(.menu).fixedSize().disabled(d.busy)
                    Text(d.format.help).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if d.format == .mp3 {
                        Toggle(isOn: $d.vbr) {
                            Text("\(Text("Use VBR? ").bold())\(Text("(unchecked = constant bitrate, up to 320 kbps, matched to the source)").font(.caption).foregroundStyle(.secondary))")
                        }.disabled(d.busy).fixedSize(horizontal: false, vertical: true)
                    }
                    Toggle(isOn: $d.squareArt) {
                        Text("\(Text("Square cover art ").bold())\(Text("(crops the wide video thumbnail so it fits music players)").font(.caption).foregroundStyle(.secondary))")
                    }.disabled(d.busy).fixedSize(horizontal: false, vertical: true)
                    Toggle(isOn: $d.removeNonMusic) {
                        Text("\(Text("Remove non-music parts ").bold())\(Text("(YouTube only: cuts talking intros and outros using SponsorBlock community data)").font(.caption).foregroundStyle(.secondary))")
                    }.disabled(d.busy).fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 10) {
                        Button("Download to...") { d.chooseFolder() }.disabled(d.busy)
                        Text((d.downloadDir.path as NSString).abbreviatingWithTildeInPath)
                            .font(.callout).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle).help(d.downloadDir.path)
                    }
                }.padding(.leading, 4)
            }
            HStack(spacing: 8) {
                if d.url.trimmingCharacters(in: .whitespaces).isEmpty && !d.busy && d.clipboardHasText {
                    Button { d.pasteAndDownload() } label: { Label("Paste & download", systemImage: "doc.on.clipboard") }
                        .controlSize(.large).help("Download the link on your clipboard")
                }
                Button { d.start() } label: { Text(d.buttonTitle).lineLimit(1).truncationMode(.tail).frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(d.busy || d.url.trimmingCharacters(in: .whitespaces).isEmpty)
                    .keyboardShortcut(.defaultAction)
                if d.busy {
                    Button("Cancel", role: .cancel) { d.cancel() }
                        .controlSize(.large).keyboardShortcut(.cancelAction).disabled(d.cancelRequested)
                }
            }
            if d.finished {
                Text("Paste a new URL link to start again").font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
            if d.stage != .idle {
                if d.stage != .failed && d.stage != .cancelled {
                    if let f = d.fraction { ProgressView(value: f) } else { ProgressView().progressViewStyle(.linear) }
                }
                Text(d.cancelRequested && d.busy ? "Cancelling…" : d.message).font(.callout).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .foregroundStyle(d.stage == .failed ? Color.red : d.stage == .done ? Color.green : Color.secondary)
                if d.stage == .failed && d.oldYtdlpNotice == nil {
                    HStack(spacing: 8) {
                        Button("Update yt-dlp") { d.runUpdate() }.disabled(d.updating)
                        Text("An outdated yt-dlp is the most common cause of download errors.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if d.stage == .done, let q = d.quality {
                    HStack(alignment: .top, spacing: 12) {
                        if let a = d.art {
                            Image(nsImage: a).resizable().scaledToFill().frame(width: 96, height: 96)
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                                .overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
                        }
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Quality: " + q.summary).font(.callout.bold()).fixedSize(horizontal: false, vertical: true)
                            Text(q.note).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    HStack {
                        Button("Open file") { d.openFile() }
                        Button("Show in folder") { d.showInFolder() }
                    }
                }
            }
        }
        .padding(24)
        // Width: starts at 560, user can drag it wider. Height: always exactly fits the content,
        // so the window grows when advanced options or results appear and shrinks when they go away.
        .frame(minWidth: 480, idealWidth: 560, maxWidth: .infinity, alignment: .topLeading)
        .fixedSize(horizontal: false, vertical: true)
        .dropDestination(for: URL.self) { links, _ in return d.dropped(links) }
        .onAppear { d.refreshClipboard(); d.checkYtdlpAge() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in d.stopForQuit() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in d.refreshClipboard() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    // Clicking a "Download finished" notification shows the file in Finder.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let path = response.notification.request.content.userInfo["path"] as? String
        DispatchQueue.main.async {
            if let p = path { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: p)]) }
        }
        completionHandler()
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}

@main
struct QuickCrateApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        WindowGroup("Quick Crate") { ContentView() }.windowResizability(.contentSize)
    }
}
