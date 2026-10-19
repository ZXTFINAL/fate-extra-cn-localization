import AppKit
import Foundation

guard (3...5).contains(CommandLine.arguments.count) else {
  fputs("usage: render_font_glyphs.swift <glyph-list.txt> <glyphs.raw> [cell-size] [font-size]\n", stderr)
  exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let cellSize = CommandLine.arguments.count >= 4 ? Int(CommandLine.arguments[3]) ?? 0 : 16
let fontSize = CommandLine.arguments.count >= 5 ? Double(CommandLine.arguments[4]) ?? 0 : 13
guard (1...256).contains(cellSize), fontSize > 0, fontSize <= Double(cellSize) else {
  fputs("invalid glyph cell or font size\n", stderr)
  exit(2)
}
let contents = try String(contentsOf: inputURL, encoding: .utf8)
let glyphs = contents.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
// Match the heavier strokes of the original PSP glyph atlas. The regular
// Hiragino GB face looked visibly thinner beside the game's built-in glyphs.
let font = NSFont(name: "HiraginoSansGB-W6", size: fontSize) ?? NSFont.systemFont(ofSize: fontSize, weight: .semibold)
var output = Data()
var count = UInt32(glyphs.count).littleEndian
withUnsafeBytes(of: &count) { output.append(contentsOf: $0) }

for glyph in glyphs {
  guard glyph.count == 1, let scalar = glyph.unicodeScalars.first else {
    fputs("each glyph entry must be exactly one Unicode scalar\n", stderr)
    exit(2)
  }
  if !font.coveredCharacterSet.contains(scalar) {
    fputs("font does not contain U+\(String(scalar.value, radix: 16).uppercased())\n", stderr)
    exit(3)
  }

  guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: cellSize,
    pixelsHigh: cellSize,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: cellSize * 4,
    bitsPerPixel: 32
  ), let pixels = bitmap.bitmapData else {
    fputs("could not allocate glyph bitmap\n", stderr)
    exit(4)
  }

  NSGraphicsContext.saveGraphicsState()
  let context = NSGraphicsContext(bitmapImageRep: bitmap)!
  NSGraphicsContext.current = context
  context.imageInterpolation = .high
  context.cgContext.clear(CGRect(x: 0, y: 0, width: cellSize, height: cellSize))
  let attributes: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor.white,
  ]
  let size = (glyph as NSString).size(withAttributes: attributes)
  let x = (Double(cellSize) - size.width) / 2.0
  let y = (Double(cellSize) - size.height) / 2.0
  (glyph as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
  context.flushGraphics()
  NSGraphicsContext.restoreGraphicsState()

  for row in 0..<cellSize {
    for column in 0..<cellSize {
      output.append(pixels[row * cellSize * 4 + column * 4 + 3])
    }
  }
}

try output.write(to: outputURL)
