import Foundation
import Vision
import AppKit

let paths = try JSONDecoder().decode([String].self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
var output: [[String: Any]] = []
for (i, path) in paths.enumerated() {
  autoreleasepool {
    do {
      let request = VNRecognizeTextRequest()
      request.recognitionLevel = .accurate
      request.recognitionLanguages = ["ja-JP", "en-US"]
      request.usesLanguageCorrection = false
      request.minimumTextHeight = 0.008
      let image = NSImage(contentsOfFile: path)!
      var rect = NSRect(origin: .zero, size: image.size)
      let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil)!
      try VNImageRequestHandler(cgImage: cg).perform([request])
      let w = Double(cg.width), h = Double(cg.height)
      let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": text.string, "confidence": text.confidence,
                "box": [box.minX * w, (1 - box.maxY) * h, box.width * w, box.height * h]]
      }
      output.append(["path": path, "lines": lines])
    } catch {
      output.append(["path": path, "error": String(describing: error)])
    }
  }
  if i % 25 == 0 { fputs("OCR \(i)/\(paths.count)\n", stderr) }
}
let data = try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted, .sortedKeys])
try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
