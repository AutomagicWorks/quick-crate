import AppKit

// Draws the app icon: waveform bars pouring into a downward "play" triangle (play + download).
let S = 1024
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: S, pixelsHigh: S, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

// Apple's macOS icon grid: an 824 x 824 squircle centred on a 1024 canvas, with no shadow outside it
// (macOS adds its own). Matching this shape keeps macOS 26 from putting the icon in a gray frame.
// The squircle is a superellipse (exponent 5), which approximates Apple's continuous-corner shape.
func superellipse(center c: CGPoint, radius r: CGFloat, exponent n: CGFloat = 5, steps: Int = 720) -> CGPath {
    let path = CGMutablePath()
    for i in 0...steps {
        let t = CGFloat(i) / CGFloat(steps) * 2 * .pi
        let ct = cos(t), st = sin(t)
        let x = c.x + r * (ct < 0 ? -1 : 1) * pow(abs(ct), 2 / n)
        let y = c.y + r * (st < 0 ? -1 : 1) * pow(abs(st), 2 / n)
        if i == 0 { path.move(to: CGPoint(x: x, y: y)) } else { path.addLine(to: CGPoint(x: x, y: y)) }
    }
    path.closeSubpath()
    return path
}
let squircle = superellipse(center: CGPoint(x: 512, y: 512), radius: 412)

// Background gradient
ctx.saveGState()
ctx.addPath(squircle); ctx.clip()
let cs = CGColorSpaceCreateDeviceRGB()
let grad = CGGradient(colorsSpace: cs, colors: [NSColor(red: 1.0, green: 0.30, blue: 0.36, alpha: 1).cgColor,
                                                NSColor(red: 0.72, green: 0.06, blue: 0.18, alpha: 1).cgColor] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 100), options: [])
// Soft top gloss
let gloss = CGGradient(colorsSpace: cs, colors: [NSColor.white.withAlphaComponent(0.22).cgColor,
                                                 NSColor.white.withAlphaComponent(0).cgColor] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(gloss, start: CGPoint(x: 512, y: 924), end: CGPoint(x: 512, y: 560), options: [])

// Waveform bars (fade toward the edges)
let heights: [CGFloat] = [90, 170, 260, 370, 260, 170, 90]
let alphas: [CGFloat] = [0.50, 0.65, 0.82, 1.0, 0.82, 0.65, 0.50]
let bw: CGFloat = 46, gap: CGFloat = 30
let total = CGFloat(heights.count) * bw + CGFloat(heights.count - 1) * gap
var x = 512 - total / 2
for (i, h) in heights.enumerated() {
    let r = CGRect(x: x, y: 690 - h / 2, width: bw, height: h)
    ctx.setFillColor(NSColor.white.withAlphaComponent(alphas[i]).cgColor)
    ctx.addPath(CGPath(roundedRect: r, cornerWidth: bw / 2, cornerHeight: bw / 2, transform: nil)); ctx.fillPath()
    x += bw + gap
}

// Downward play triangle with rounded corners
let tri = CGMutablePath()
tri.move(to: CGPoint(x: 352, y: 470)); tri.addLine(to: CGPoint(x: 672, y: 470)); tri.addLine(to: CGPoint(x: 512, y: 270)); tri.closeSubpath()
ctx.setFillColor(NSColor.white.cgColor); ctx.setStrokeColor(NSColor.white.cgColor)
ctx.setLineWidth(44); ctx.setLineJoin(.round)
ctx.addPath(tri); ctx.drawPath(using: .fillStroke)

// Tray line
let tray = CGRect(x: 342, y: 188, width: 340, height: 34)
ctx.setFillColor(NSColor.white.withAlphaComponent(0.9).cgColor)
ctx.addPath(CGPath(roundedRect: tray, cornerWidth: 17, cornerHeight: 17, transform: nil)); ctx.fillPath()
ctx.restoreGState()
NSGraphicsContext.restoreGraphicsState()

try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
