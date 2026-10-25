import AppKit
import Foundation

guard CommandLine.arguments.count >= 5 else {
  fputs("usage: render_hd_font_glyphs.swift <glyph-list.txt> <glyphs.raw> <cell-size> <font-size> [font-name... ]\n", stderr)
  exit(2)
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let cellSize = Int(CommandLine.arguments[3]) ?? 0
let fontSize = Double(CommandLine.arguments[4]) ?? 0
let fontNames = Array(CommandLine.arguments.dropFirst(5)).isEmpty
  ? ["HiraginoSansGB-W6", "PingFangSC-Semibold", "Apple Symbols"]
  : Array(CommandLine.arguments.dropFirst(5))

guard (1...256).contains(cellSize), fontSize > 0, fontSize <= Double(cellSize) else {
  fputs("invalid glyph cell or font size\n", stderr)
  exit(2)
}

let contents = try String(contentsOf: inputURL, encoding: .utf8)
let glyphs = contents.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
let fonts = fontNames.compactMap { NSFont(name: $0, size: fontSize) }
guard !fonts.isEmpty else {
  fputs("none of the requested fonts are installed\n", stderr)
  exit(2)
}

var output = Data()
var count = UInt32(glyphs.count).littleEndian
withUnsafeBytes(of: &count) { output.append(contentsOf: $0) }
var fallbackCounts: [String: Int] = [:]
var missing: [String] = []

for glyph in glyphs {
  guard glyph.count == 1, let scalar = glyph.unicodeScalars.first else {
    fputs("each glyph entry must be exactly one Unicode scalar\n", stderr)
    exit(2)
  }
  guard let font = fonts.first(where: { $0.coveredCharacterSet.contains(scalar) }) else {
    missing.append(String(format: "U+%04X", scalar.value))
    continue
  }
  fallbackCounts[font.fontName, default: 0] += 1

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

guard missing.isEmpty else {
  fputs("font fallback chain lacks glyphs: \(missing.joined(separator: ", "))\n", stderr)
  exit(3)
}

try output.write(to: outputURL)
for (font, count) in fallbackCounts.sorted(by: { $0.key < $1.key }) {
  print("\(font): \(count) glyphs")
}
