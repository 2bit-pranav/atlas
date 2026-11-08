// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import { clockOf, isYouTubeVideo, seconds, transcriptLines } from "./youtube"
import { pointers } from "./pointers"
import { go, point } from "./highlight"

describe("YouTube", () => {
  it("knows a video by its address", () => {
    expect(isYouTubeVideo("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")).toBe(true)
    expect(isYouTubeVideo("https://www.youtube.com/shorts/abc123")).toBe(true)
    expect(isYouTubeVideo("https://www.youtube.com/results?search_query=x")).toBe(false)
    expect(isYouTubeVideo("https://notyoutube.com/watch?v=x")).toBe(false)
  })

  it("reads the transcript YouTube shows, in either of its layouts", () => {
    document.body.innerHTML = `
      <ytd-transcript-segment-renderer><div class="segment-timestamp">0:05</div><yt-formatted-string>Welcome back</yt-formatted-string></ytd-transcript-segment-renderer>
      <transcript-segment-view-model><span class="ytwTranscriptSegmentViewModelTimestamp">12:34</span><span>the setup part</span></transcript-segment-view-model>`
    expect(transcriptLines(document, 10)).toEqual(["[0:05] Welcome back", "[12:34] the setup part"])
    expect(transcriptLines()).toEqual(["[0:05] Welcome back the setup part"])          // grouped: one time per passage
    // A second copy of the transcript (another layout) is not read again.
    document.body.insertAdjacentHTML("beforeend", `<ytd-transcript-segment-renderer><div class="segment-timestamp">0:05</div>Welcome back</ytd-transcript-segment-renderer>`)
    expect(transcriptLines(document, 10)).toEqual(["[0:05] Welcome back", "[12:34] the setup part"])
  })

  it("turns a cited time into a place that plays the video from there", () => {
    expect([seconds("12:34"), seconds("1:02:03"), clockOf(3723)]).toEqual([754, 3723, "1:02:03"])
    expect(pointers("He explains it at [12:34] and again at [1:02:03].")).toEqual([{ time: 754, label: "12:34" }, { time: 3723, label: "1:02:03" }])
    document.body.innerHTML = `<video></video>`
    const { places } = point([{ time: 754, label: "12:34" }])
    expect(places[0]).toMatchObject({ found: true, how: "time", kind: "Video" })
    expect(go(0).ok).toBe(true)
    expect(document.querySelector("video")!.currentTime).toBe(754)
  })
})
