<img src="./frontend/public/poster.png" width="300" />

> *"What you most want, is what you most can't have. And what you most can't have, is what you already had, and lost."* — Christopher Nolan

For someone living with memory issues, recognizing a familiar face does not always mean remembering a name. In Christopher Nolan's *Memento*, Leonard Shelby had to rely on a collection of Polaroid photos, handwritten notes tattooed onto his skin, and scattered files simply to piece together who was standing in front of him. We built **Enlight** to serve as that external memory system, brought into the modern age through ambient intelligent technology rather than fading paper notes.

## What is it exactly?
**Enlight** is an AI-powered visual companion and private memory timeline designed to help individuals living with memory issues navigate daily social interactions and retain their independence.

Through a live camera feed, Enlight performs real-time face recognition and displays immediate contextual notes about the person in view. As dialogue occurs, it tracks facial movement and audio timing to attribute speech accurately, while Gemini transcribes and takes structured notes on the fly. It automatically extracts names, personal details, and shared experiences, updating the live screen in real time and saving every detail to local profiles. Beyond social recognition, Enlight includes a proactive reminder and navigation system. If a user becomes disoriented, gets lost, or wanders while traveling, Enlight provides reassuring directions, clarifies where they are headed, and surfaces upcoming daily tasks.

At its core, Enlight also serves as a personal social network like Facebook, built to reconstruct lost pieces of a person's life story. It seamlessly pairs automated conversation logs from above with personal notes written and edited by you. By scrolling back through your notes, our goal is to allow individuals living with memory issues to revisit past interactions, recall familiar faces, and reconnect with meaningful memories that might otherwise slip away.

## What we achieved
Nothing about building Enlight was clean. High-speed transcription gave us words in milliseconds, but matching those words to moving lips broke down the second two voices overlapped or an audio buffer drifted out of sync. We spent hours watching the system guess wildly before we locked down strict confidence thresholds, including one memorable test run where the model began hallucinating Russian and Chinese mid-recording. By the end, that friction produced an engine that quietly does what matters: recognizes faces across restarts, learns names and personal details directly from casual introductions, and stays silent when it is not sure.

Hardware forced us to get scrappy. We did not have sleek smart glasses, so we stitched everyday devices into an assistive rig. To feed live GPS into our wandering alerts, we picked up Swift on the spot and built a companion phone app to beam coordinates straight to the laptop in real time.

All of this was held together by four strangers juggling Linux, macOS, native Windows, and WSL. A camera pipeline that worked on one screen would instantly crash on the next due to broken permissions and routing bugs. We had four completely different ways of coding and zero shared history, but whenever something broke, someone else jumped in with a workaround. In thirty+ chaotic hours, we turned four mismatched operating systems into one unified tool.

## How it was made
- **Vision & Tracking**: Python, OpenCV, and MediaPipe handle real-time multi-face detection, persistent feature recognition, and lip-sync/mouth-activity tracking to accurately attribute spoken turns to visible speakers.
- **Audio & Transcription**: ElevenLabs Scribe Realtime provides ultra-low-latency speech transcription, streaming live conversation directly to our background coordinator.
- **Cognitive Processing & Intelligence**: Google Gemini analyzes live conversational transcripts and audio to extract names, facts, evidence quotes, and social context without storing raw audio.
- **Knowledge Graph Engine**: A custom GraphDB and relationship graph model structured memory nodes, edges, and interaction depth between enrolled people.
- **Database & Persistence**: MongoDB manages durable identity records, enrolled face pictures, linked notes, and timeline posts while keeping files indexed locally.
- **Frontend & Mapping**: Built with Next.js, React, Tailwind CSS, and Google Maps API (`@googlemaps/js-api-loader`) for real-time location tracking, memory mapping, and interactive timeline visualization.
- **Hand-Crafted Artwork**: We even found time to add a custom hand-drawn canvas created without generative AI. We hope you love our elephant, because it never forgets!

## What's next for Enlight
Our immediate priority is form factor: moving away from clunky laptop setups toward something people can seamlessly carry around, like lightweight smart glasses that offer fast, clear cues throughout the day without getting in the way.

Just as importantly, we want to step outside our own engineering bubble. Most of what we built this weekend came from a hunch, guessing at what memory loss feels like and relying on instincts rather than lived reality. Moving forward, we want to listen, spend time with caregivers, and consult specialists to genuinely understand what people living with memory issues face every day. Designing for dignity means replacing guesswork with real solutions, so Enlight can grow into a tool shaped by the actual needs of the community rather than just good intentions.

## How to run the product
Run the services in separate terminals in the following order:

1. **Backend Server**
   ```bash
   uvicorn backend.main:app --reload
   ```

2. **Tracking Engine**
   ```bash
   python -m tracker_engine --camera 1
   ```

3. **Frontend Client**
   ```bash
   npm run dev
   ```


   
