// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import { clockOf, isYouTubeVideo, seconds, transcriptLines, videoId } from "./youtube"
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
    expect(pointers("He explains it at [12:34] and again at [1:02:03].")).toMatchObject([{ time: 754, label: "12:34" }, { time: 3723, label: "1:02:03" }])
    document.body.innerHTML = `<video></video>`
    const { places } = point([{ time: 754, label: "12:34" }])
    expect(places[0]).toMatchObject({ found: true, how: "time", kind: "12:34" })
    expect(go(0).ok).toBe(true)
    expect(document.querySelector("video")!.currentTime).toBe(754)
  })
})

describe("moments in a video, labelled by the answer", () => {
  it("names each time by what the answer says happens there", async () => {
    const { pointers } = await import("./pointers")
    const answer = "Key moments:\n- [0:04] **Why digits are hard** for a program to read\n- [4:10]: The layered structure of the network\n\n" +
      "He first shows a sloppy three. Later, at [12:30], he explains how weights and biases set each neuron's activation, " +
      "which is the core of the video and takes a while to build up properly with the pictures he uses."
    const labels = pointers(answer).map((p) => ("time" in p ? [p.label, p.about ?? ""] : ["", ""]))
    expect(labels.slice(0, 2)).toEqual([["0:04", "Why digits are hard for a program to read"], ["4:10", "The layered structure of the network"]])
    expect(labels[2][0]).toBe("12:30")
    expect(labels[2][1].startsWith("Later, he explains how weights and biases set each neuron's activation")).toBe(true)
    expect(labels[2][1].length).toBeLessThanOrEqual(110)
  })
})

describe("videoId", () => {
  it("keys the kept read by the video, not the address", () => {
    expect(videoId("https://www.youtube.com/watch?v=aircAruvnKk&t=30s")).toBe("aircAruvnKk")
    expect(videoId("https://www.youtube.com/shorts/abc_D-1")).toBe("abc_D-1")
    expect(videoId("https://www.youtube.com/feed")).toBe("")
    expect(videoId("not a url")).toBe("")
  })
})
