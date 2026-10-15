import Foundation
import Vision
import ImageIO
import CoreGraphics

// Apple's built-in Vision framework runs on-device; no network client is used.
let paths = try String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8).split(separator: "\n").map(String.init)
var previous: [UInt8]? = nil
for (index, path) in paths.enumerated() {
    autoreleasepool {
        do {
            let url = URL(fileURLWithPath: path)
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil), let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw NSError(domain: "Decode", code: 1) }
            var pixels = [UInt8](repeating: 0, count: 32 * 64 * 4)
            pixels.withUnsafeMutableBytes { buffer in
                let context = CGContext(data: buffer.baseAddress, width: 32, height: 64, bitsPerComponent: 8, bytesPerRow: 128, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                context.draw(image, in: CGRect(x: 0, y: 0, width: 32, height: 64))
            }
            var change = 0.0
            if let last = previous {
                for i in stride(from: 0, to: pixels.count, by: 4) {
                    for c in 0..<3 { change += Double(abs(Int(pixels[i+c]) - Int(last[i+c]))) }
                }
                change /= Double(32 * 64 * 3 * 255)
            }
            previous = pixels
            var texts: [[String: Any]] = []
            var counters: [String: Any] = [:]
            if index % 2 == 0 {
                let request = VNRecognizeTextRequest()
                request.recognitionLevel = .accurate
                request.usesLanguageCorrection = false
                request.recognitionLanguages = ["en-US"]
                try VNImageRequestHandler(cgImage: image).perform([request])
                for item in request.results ?? [] {
                    guard let candidate = item.topCandidates(1).first, candidate.confidence >= 0.65 else { continue }
                    let b = item.boundingBox
                    texts.append(["text": candidate.string, "confidence": Double(candidate.confidence), "box": [b.minX, 1-b.maxY, b.width, b.height]])
                }
            }
            if index % 2 == 0 {
                let regions: [(String, Double, Double, Double, Double)] = [
                    ("enemy_left", 0.17, 0.181, 0.105, 0.026), ("enemy_right", 0.75, 0.181, 0.105, 0.026),
                    ("own_left", 0.17, 0.618, 0.105, 0.027), ("own_right", 0.75, 0.618, 0.105, 0.027),
                    ("own_king", 0.44, 0.741, 0.12, 0.033)]
                for (name, x, y, w, h) in regions {
                    guard let crop = image.cropping(to: CGRect(x: x*Double(image.width), y: y*Double(image.height), width: w*Double(image.width), height: h*Double(image.height))) else { continue }
                    let cw = crop.width*4, ch = crop.height*4
                    let ctx = CGContext(data: nil, width: cw, height: ch, bitsPerComponent: 8, bytesPerRow: cw*4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                    ctx.interpolationQuality = .high
                    ctx.draw(crop, in: CGRect(x: 0,y: 0,width: cw,height: ch))
                    guard let large = ctx.makeImage() else { continue }
                    let req = VNRecognizeTextRequest(); req.recognitionLevel = .accurate; req.usesLanguageCorrection = false
                    req.recognitionLanguages = ["en-US"]
                    try VNImageRequestHandler(cgImage: large).perform([req])
                    let candidates = (req.results ?? []).compactMap { $0.topCandidates(1).first }
                    if candidates.count == 1, let c = candidates.first, c.confidence >= 0.9,
                       c.string.range(of: "^[0-9]{2,4}$", options: .regularExpression) != nil,
                       let value = Int(c.string), value >= 100, value <= 9999 {
                        counters[name] = ["value": value, "confidence": Double(c.confidence), "box": [x,y,w,h]]
                    }
                }
            }
            let row: [String: Any] = ["index": index, "change": change, "text": texts, "counters": counters]
            let data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            print(String(data: data, encoding: .utf8)!)
            fflush(stdout)
        } catch {
            print("{\"index\":\(index),\"error\":\"Local image recognition failed\"}")
            fflush(stdout)
        }
    }
}
