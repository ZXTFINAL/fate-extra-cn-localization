import AppKit
import Foundation

guard CommandLine.arguments.count == 7 else {
  fputs("usage: render_ui_title.swift <text> <width> <height> <font-name> <font-size> <output.raw>\n", stderr)
  exit(2)
}

let text = CommandLine.arguments[1]
guard let width = Int(CommandLine.arguments[2]), let height = Int(CommandLine.arguments[3]),
      let fontSize = Double(CommandLine.arguments[5]) else {
  fputs("invalid dimensions or font size\n", stderr)
  exit(2)
}
let fontName = CommandLine.arguments[4]
let outputURL = URL(fileURLWithPath: CommandLine.arguments[6])
let font = NSFont(name: fontName, size: fontSize) ?? NSFont.systemFont(ofSize: fontSize)

guard let bitmap = NSBitmapImageRep(
  bitmapDataPlanes: nil,
  pixelsWide: width,
  pixelsHigh: height,
  bitsPerSample: 8,
  samplesPerPixel: 4,
  hasAlpha: true,
  isPlanar: false,
  colorSpaceName: .deviceRGB,
  bytesPerRow: width * 4,
  bitsPerPixel: 32
), let pixels = bitmap.bitmapData else {
  fputs("could not allocate title bitmap\n", stderr)
  exit(3)
}

NSGraphicsContext.saveGraphicsState()
let context = NSGraphicsContext(bitmapImageRep: bitmap)!
NSGraphicsContext.current = context
context.imageInterpolation = .high
context.cgContext.clear(CGRect(x: 0, y: 0, width: width, height: height))
let attributes: [NSAttributedString.Key: Any] = [
  .font: font,
  .foregroundColor: NSColor.white,
]
let measured = (text as NSString).size(withAttributes: attributes)
let x = (Double(width) - measured.width) / 2.0
let y = (Double(height) - measured.height) / 2.0
(text as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

var output = Data(capacity: width * height)
for row in 0..<height {
  for column in 0..<width {
    output.append(pixels[row * width * 4 + column * 4 + 3])
  }
}
try output.write(to: outputURL)
