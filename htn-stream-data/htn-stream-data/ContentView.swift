import SwiftUI

struct ContentView: View {
    @State private var streamer = MotionStreamer()
    @State private var isStreaming = false
    @State private var statusText = "Ready to start"

    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            
            VStack(spacing: 28) {
                VStack(spacing: 10) {
                    Image(systemName: isStreaming ? "location.fill" : "location.slash")
                        .font(.system(size: 60))
                        .foregroundColor(isStreaming ? .blue : .secondary)
                    
                    Text(isStreaming ? "Streaming Active" : "Stream Paused")
                        .font(.title2)
                        .bold()
                    
                    Text(statusText)
                        .font(.system(.footnote, design: .monospaced))
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }
                
                Button(action: {
                    if isStreaming {
                        streamer.stop()
                        isStreaming = false
                        statusText = "Stream Paused"
                    } else {
                        streamer.start()
                        isStreaming = true
                        statusText = "Starting stream..."
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
                statusText = data
            }
        }
    }
}
