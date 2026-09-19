import Foundation
import CoreMotion
import CoreLocation
import Network

@MainActor
final class MotionStreamer: NSObject, CLLocationManagerDelegate {
    private let motionManager = CMMotionManager()
    private let locationManager = CLLocationManager()
    private var connection: NWConnection?
    
    // Put your Mac's current Wi-Fi IP address here
    private let macHost = NWEndpoint.Host("10.37.117.248")
    private let macPort = NWEndpoint.Port(integerLiteral: 5005)
    
    private var currentLat: Double = 0.0
    private var currentLon: Double = 0.0
    private var currentAlt: Double = 0.0
    
    var onDataUpdate: ((String) -> Void)?
    private(set) var isStreaming = false
    
    override init() {
        super.init()
        setupUDP()
        
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.distanceFilter = kCLDistanceFilterNone
        locationManager.requestWhenInUseAuthorization()
    }
    
    private func setupUDP() {
        let params = NWParameters.udp
        connection = NWConnection(host: macHost, port: macPort, using: params)
        connection?.start(queue: .global(qos: .userInteractive))
    }
    
    func start() {
        guard !isStreaming else { return }
        isStreaming = true
        
        // Check if there is an existing location cached by the OS
        if let cached = locationManager.location {
            self.currentLat = cached.coordinate.latitude
            self.currentLon = cached.coordinate.longitude
            self.currentAlt = cached.altitude
        }
        
        locationManager.startUpdatingLocation()
        startMotion()
    }
    
    func stop() {
        isStreaming = false
        motionManager.stopDeviceMotionUpdates()
        locationManager.stopUpdatingLocation()
    }
    
    private func startMotion() {
        guard motionManager.isDeviceMotionAvailable else { return }
        
        // 1.0 second intervals
        motionManager.deviceMotionUpdateInterval = 1.0
        
        motionManager.startDeviceMotionUpdates(using: .xMagneticNorthZVertical, to: .main) { [weak self] motion, _ in
            guard let self = self, self.isStreaming, let motion = motion else { return }
            
            let acc = motion.userAcceleration
            let yaw = motion.attitude.yaw
            let headingDeg = (yaw * 180.0 / .pi + 360.0).truncatingRemainder(dividingBy: 360.0)
            
            let payload = String(
                format: "%.2f,%.2f,%.2f|%.1f|%.6f,%.6f,%.1f",
                acc.x, acc.y, acc.z,
                headingDeg,
                self.currentLat, self.currentLon, self.currentAlt
            )
            
            self.send(payload)
            self.onDataUpdate?(payload)
        }
    }
    
    private func send(_ text: String) {
        guard let data = text.data(using: .utf8) else { return }
        connection?.send(content: data, completion: .idempotent)
    }
    
    // MARK: - CLLocationManagerDelegate
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        Task { @MainActor in
            self.currentLat = loc.coordinate.latitude
            self.currentLon = loc.coordinate.longitude
            self.currentAlt = loc.altitude
            print("📍 Real GPS Acquired: \(loc.coordinate.latitude), \(loc.coordinate.longitude)")
        }
    }
    
    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("Location manager error: \(error.localizedDescription)")
    }
}
