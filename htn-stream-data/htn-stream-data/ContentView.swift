import SwiftUI

struct ContentView: View {
    @State private var streamer = MotionStreamer()
    @State private var isStreaming = false
    @State private var lat: Double = 0.0
    @State private var lon: Double = 0.0
    @State private var alt: Double = 0.0
    @State private var heading: Double = 0.0
    @State private var gpsLocked = false

    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            
            VStack(spacing: 24) {
                // Header icon
                Image(systemName: isStreaming ? "location.fill" : "location.slash")
                    .font(.system(size: 60))
                    .foregroundColor(isStreaming ? .blue : .secondary)

                Text(isStreaming ? "Streaming Active" : "Stream Paused")
                    .font(.title2)
                    .bold()

                // GPS Status Card
                VStack(spacing: 10) {
                    HStack {
                        Circle()
                            .fill(gpsLocked ? Color.green : Color.orange)
                            .frame(width: 10, height: 10)
                        Text(gpsLocked ? "GPS Locked" : "Acquiring GPS fix...")
                            .font(.subheadline)
                            .bold()
                            .foregroundColor(gpsLocked ? .green : .orange)
                    }

                    if gpsLocked {
                        VStack(alignment: .leading, spacing: 4) {
                            Label(String(format: "Lat:  %.6f", lat), systemImage: "arrow.up.arrow.down")
                            Label(String(format: "Lon: %.6f", lon), systemImage: "arrow.left.arrow.right")
                            Label(String(format: "Alt:  %.1f m", alt), systemImage: "arrow.up.to.line")
                        }
                        .font(.system(.body, design: .monospaced))
                        .foregroundColor(.primary)
                    }

                    Label(String(format: "Heading: %.1f°", heading), systemImage: "safari")
                        .font(.system(.footnote, design: .monospaced))
                        .foregroundColor(.secondary)
                }
                .padding()
                .frame(maxWidth: .infinity)
                .background(Color(.secondarySystemBackground))
                .cornerRadius(14)
                .padding(.horizontal, 24)

                // Start / Stop Button
                Button(action: {
                    if isStreaming {
                        streamer.stop()
                        isStreaming = false
                    } else {
                        streamer.start()
                        isStreaming = true
                    }
                }) {
                    Text(isStreaming ? "STOP STREAM" : "START STREAM")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(isStreaming ? Color.red : Color.blue)
                        .foregroundColor(.white)
                        .cornerRadius(12)
                }
                .padding(.horizontal, 40)
            }
        }
        .onAppear {
            streamer.onDataUpdate = { data in
                // Parse: "accX,accY,accZ|heading|lat,lon,alt"
                let parts = data.split(separator: "|")
                guard parts.count == 3 else { return }
                heading = Double(parts[1]) ?? 0.0
                let gps = parts[2].split(separator: ",")
                if gps.count == 3,
                   let la = Double(gps[0]),
                   let lo = Double(gps[1]),
                   let al = Double(gps[2]) {
                    lat = la
                    lon = lo
                    alt = al
                    gpsLocked = (la != 0.0 || lo != 0.0)
                }
            }
        }
    }
}
