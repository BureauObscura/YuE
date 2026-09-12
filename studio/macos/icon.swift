import AppKit
import Foundation

// Original vector artwork for the local app. Rendered at each Dock icon size.
let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
let sizes = [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
             (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
             (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
             (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
             (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]
for (pixels, name) in sizes {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                  colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
    let base = NSBezierPath(roundedRect: NSRect(x: 52, y: 52, width: 920, height: 920), xRadius: 218, yRadius: 218)
    let background = NSGradient(starting: NSColor(red: 0.21, green: 0.23, blue: 0.20, alpha: 1), ending: NSColor(red: 0.10, green: 0.12, blue: 0.10, alpha: 1))!
    background.draw(in: base, angle: -55)
    NSColor(white: 1, alpha: 0.12).setStroke()
    base.lineWidth = 2
    base.stroke()
    let ring = NSBezierPath(ovalIn: NSRect(x: 191, y: 191, width: 642, height: 642))
    NSColor(red: 0.86, green: 0.79, blue: 0.67, alpha: 0.11).setStroke()
    ring.lineWidth = 2
    ring.stroke()
    context.cgContext.translateBy(x: 189, y: 807)
    context.cgContext.scaleBy(x: 19, y: -19)
    let outer = NSBezierPath()
    outer.move(to: NSPoint(x: 5, y: 7))
    outer.line(to: NSPoint(x: 5, y: 16))
    outer.curve(to: NSPoint(x: 17, y: 28), controlPoint1: NSPoint(x: 5, y: 22.627), controlPoint2: NSPoint(x: 10.373, y: 28))
    outer.curve(to: NSPoint(x: 29, y: 16), controlPoint1: NSPoint(x: 23.627, y: 28), controlPoint2: NSPoint(x: 29, y: 22.627))
    outer.line(to: NSPoint(x: 29, y: 7))
    outer.lineCapStyle = .round
    outer.lineWidth = 2.2
    NSColor(red: 0.961, green: 0.953, blue: 0.937, alpha: 1).setStroke()
    outer.stroke()
    let inner = NSBezierPath()
    inner.move(to: NSPoint(x: 11, y: 5))
    inner.line(to: NSPoint(x: 11, y: 16))
    inner.curve(to: NSPoint(x: 17, y: 22), controlPoint1: NSPoint(x: 11, y: 19.314), controlPoint2: NSPoint(x: 13.686, y: 22))
    inner.curve(to: NSPoint(x: 23, y: 16), controlPoint1: NSPoint(x: 20.314, y: 22), controlPoint2: NSPoint(x: 23, y: 19.314))
    inner.line(to: NSPoint(x: 23, y: 5))
    inner.lineCapStyle = .round
    inner.lineWidth = 2.2
    NSColor(red: 0.678, green: 0.290, blue: 0.208, alpha: 1).setStroke()
    inner.stroke()
    let center = NSBezierPath()
    center.move(to: NSPoint(x: 17, y: 3))
    center.line(to: NSPoint(x: 17, y: 19))
    center.lineCapStyle = .round
    center.lineWidth = 2.2
    NSColor(red: 0.961, green: 0.953, blue: 0.937, alpha: 1).setStroke()
    center.stroke()
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name))
}
