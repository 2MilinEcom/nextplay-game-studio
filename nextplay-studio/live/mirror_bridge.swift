import Foundation
import AppKit
import ApplicationServices
import ScreenCaptureKit
import Vision
import ImageIO
import UniformTypeIdentifiers

// No permission prompts: report missing grants and wait for the user to reconnect.
@main struct Bridge {
    static let bundle = "com.apple.ScreenContinuity"
    static var sequence = 0
    static var lastCapture = Date.distantPast
    static var lastWindow: SCWindow? = nil
    static var lastRect: CGRect? = nil
    static var imageSize = CGSize.zero
    static func emit(_ value: [String:Any]) {
        if let data = try? JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]),let s=String(data:data,encoding:.utf8) { print(s); fflush(stdout) }
    }
    static func ocr(_ image: CGImage) throws -> [[String:Any]] {
        let request=VNRecognizeTextRequest();request.recognitionLevel = .accurate;request.usesLanguageCorrection=false;request.recognitionLanguages=["en-US"]
        try VNImageRequestHandler(cgImage:image).perform([request])
        return (request.results ?? []).compactMap { obs in
            guard let c=obs.topCandidates(1).first,c.confidence >= 0.65 else{return nil}
            let b=obs.boundingBox
            return ["text":c.string,"confidence":Double(c.confidence),"box":[Double(b.minX),Double(1-b.maxY),Double(b.width),Double(b.height)]]
        }
    }
    static func main() async {
        while let line=readLine() {
            do {
                guard let data=line.data(using:.utf8),let req=try JSONSerialization.jsonObject(with:data) as? [String:Any],let command=req["command"] as? String else {throw NSError(domain:"Invalid request",code:1)}
                if command == "status" {emit(["screen_permission":CGPreflightScreenCaptureAccess(),"input_permission":AXIsProcessTrusted(),"front_app":NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "unknown"]);continue}
                if command == "analyze" {
                    guard let path=req["path"] as? String,let source=CGImageSourceCreateWithURL(URL(fileURLWithPath:path) as CFURL,nil),let image=CGImageSourceCreateImageAtIndex(source,0,nil) else {throw NSError(domain:"Unreadable image",code:1)}
                    if req["fast"] as? Bool == true {
                        var text:[[String:Any]]=[]
                        for region in [CGRect(x:0.80,y:0.075,width:0.20,height:0.05),CGRect(x:0.24,y:0.935,width:0.10,height:0.038)] {
                            let rect=CGRect(x:region.minX*Double(image.width),y:region.minY*Double(image.height),width:region.width*Double(image.width),height:region.height*Double(image.height))
                            guard let crop=image.cropping(to:rect) else {continue}
                            let ctx=CGContext(data:nil,width:crop.width*4,height:crop.height*4,bitsPerComponent:8,bytesPerRow:crop.width*16,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
                            ctx.draw(crop,in:CGRect(x:0,y:0,width:crop.width*4,height:crop.height*4))
                            guard let enlarged=ctx.makeImage() else {continue}
                            for var item in try ocr(enlarged) {
                                if let b=item["box"] as? [Double] {item["box"]=[region.minX+b[0]*region.width,region.minY+b[1]*region.height,b[2]*region.width,b[3]*region.height]}
                                text.append(item)
                            }
                        }
                        emit(["text":text]);continue
                    }
                    emit(["text":try ocr(image)]);continue
                }
                if command == "focus" {
                    let app=NSRunningApplication.runningApplications(withBundleIdentifier:bundle).first
                    emit(["focused":app?.activate(options:[]) ?? false]);continue
                }
                if command == "capture" {
                    guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier != "com.apple.loginwindow" else {emit(["error":"Mac is locked; capture and input stopped","blocked":true]);continue}
                    guard CGPreflightScreenCaptureAccess() else {emit(["error":"Screen recording permission missing","blocked":true]);continue}
                    _ = NSApplication.shared
                    let content=try await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:true)
                    let windows=content.windows.filter {$0.owningApplication?.bundleIdentifier == bundle && $0.frame.width>150 && $0.frame.height>300}
                    guard windows.count == 1,let window=windows.first else {emit(["error":"One visible iPhone Mirroring window is required","blocked":true]);continue}
                    let filter=SCContentFilter(desktopIndependentWindow:window);let config=SCStreamConfiguration();config.width=Int(window.frame.width*2);config.height=Int(window.frame.height*2);config.showsCursor=false
                    let image=try await SCScreenshotManager.captureImage(contentFilter:filter,configuration:config)
                    guard let path=req["path"] as? String,path.hasPrefix("/"),let destination=CGImageDestinationCreateWithURL(URL(fileURLWithPath:path) as CFURL,UTType.png.identifier as CFString,1,nil) else {throw NSError(domain:"Invalid image destination",code:1)}
                    CGImageDestinationAddImage(destination,image,nil);guard CGImageDestinationFinalize(destination) else {throw NSError(domain:"Unable to save frame",code:1)}
                    sequence+=1;lastCapture=Date();lastWindow=window;lastRect=window.frame;imageSize=CGSize(width:image.width,height:image.height)
                    emit(["sequence":sequence,"width":image.width,"height":image.height,"window":[window.frame.minX,window.frame.minY,window.frame.width,window.frame.height]])
                    continue
                }
                if command == "tap" || command == "play" {
                    guard AXIsProcessTrusted(),NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundle,
                          Date().timeIntervalSince(lastCapture)<0.5,req["sequence"] as? Int == sequence,
                          let window=lastWindow,let frame=lastRect,
                          let crop=req["crop"] as? [Double],crop.count==4,
                          let point=req["point"] as? [Double],point.count==2,
                          point.allSatisfy({$0>=0 && $0<=1}),crop.allSatisfy({$0>=0}),
                          crop[0]+crop[2]<=imageSize.width,crop[1]+crop[3]<=imageSize.height else {emit(["error":"Input withheld: permission, foreground, freshness or calibration gate failed","blocked":true]);continue}
                    // Recheck window geometry before global input; moved windows fail closed.
                    let content=try await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:true)
                    guard content.windows.contains(where: {$0.windowID==window.windowID && $0.frame==frame}),NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundle,
                          Date().timeIntervalSince(lastCapture)<0.5 else {emit(["error":"Window changed or frame stale","blocked":true]);continue}
                    let location=CGPoint(x:frame.minX+(crop[0]+point[0]*crop[2])*frame.width/imageSize.width,y:frame.minY+(crop[1]+point[1]*crop[3])*frame.height/imageSize.height)
                    guard let down=CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:location,mouseButton:.left),let up=CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:location,mouseButton:.left) else {throw NSError(domain:"Input construction failed",code:1)}
                    if command == "play" {
                        guard let slot=req["slot"] as? Int,(1...4).contains(slot) else {emit(["error":"Invalid hand slot","blocked":true]);continue}
                        let sx=0.314+0.190*Double(slot-1),sy=0.89
                        let selected=CGPoint(x:frame.minX+(crop[0]+sx*crop[2])*frame.width/imageSize.width,y:frame.minY+(crop[1]+sy*crop[3])*frame.height/imageSize.height)
                        guard let sd=CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:selected,mouseButton:.left),let su=CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:selected,mouseButton:.left) else {throw NSError(domain:"Selection failed",code:1)}
                        sd.post(tap:.cghidEventTap);su.post(tap:.cghidEventTap)
                        try await Task.sleep(nanoseconds:40_000_000)
                        guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundle else {emit(["error":"Foreground changed; placement withheld","blocked":true]);continue}
                    }
                    down.post(tap:.cghidEventTap);up.post(tap:.cghidEventTap);emit(["tapped":true,"sequence":sequence]);continue
                }
                emit(["error":"Unsupported command","blocked":true])
            } catch {emit(["error":String(describing:error),"blocked":true])}
        }
    }
}
