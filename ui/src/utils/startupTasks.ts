type RssItem = {
  title: string;
};

type RssResponse = {
  status: string;
  items: RssItem[];
};

export async function runStartupRoutine(addLog: (log: string) => void): Promise<string> {
  addLog("[Startup] Initiating Morning Routine...");
  addLog("[Startup] Fetching top headlines from Times of India...");

  try {
    // We use a free public RSS-to-JSON API to bypass frontend CORS restrictions
    // and grab the live Times of India Top Stories feed.
    const rssUrl = "https://timesofindia.indiatimes.com/rssfeedstopstories.cms";
    const apiUrl = `https://api.rss2json.com/v1/api.json?rss_url=${encodeURIComponent(rssUrl)}`;
    
    const res = await fetch(apiUrl);
    const data: RssResponse = await res.json();

    if (data.status !== "ok") {
        throw new Error("News feed unavailable");
    }

    // Grab the first 5 news items
    const top5Items = data.items.slice(0, 5);
    const headlines = top5Items.map((item) => item.title);

    addLog("[Startup] Headlines retrieved successfully.");
    
    // Clean, proper markdown formatting
    return `**Startup Task Complete.**\n\nTop items today from **Times of India**:\n\n` + 
           headlines.map((h: string, i: number) => `${i + 1}. ${h}`).join("\n");
           
  } catch (error) {
    addLog(`[Startup] 🚨 Failed: ${error}`);
    return "Failed to run startup routine.";
  }
}