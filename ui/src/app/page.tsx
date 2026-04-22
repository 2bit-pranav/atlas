"use client";

import { useMemo, useRef, useState, useEffect, type ReactNode } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import { SiDiscord, SiNotion } from "react-icons/si";

import { useAtlasWebSocket } from "@/hooks/useAtlasWebSocket";
import { runStartupRoutine } from "@/utils/startupTasks";
import { executeVesitSkill, VESIT_RESULT_SKILL_SCHEMA } from "@/utils/skillsEngine";

import styles from "./page.module.css";

/* ---------------- TYPES ---------------- */

type SidebarView =
  | "new-chat"
  | "browser-sessions"
  | "saved-memory"
  | "integrations"
  | "startup-tasks"
  | "skills";

type BrowserProfileItem = {
  id: string;
  name: string;
  domains: string[];
};

type RawProfile = {
  id: string;
  name: string;
  storedData?: string;
};

type DocumentItem = {
  id: string;
  name: string;
  size: string;
};

type ChatMessage = {
  role: "user" | "ai";
  content: string;
};

type IntegrationItem = {
  id: string;
  name: string;
  description: string;
  accentClass: string;
  logo: ReactNode;
  connectedLabel?: string;
};

type SchemaItem = {
  id: string;
  name: string;
  schema: string;
  action?: () => void;
};

/* ---------------- DATA ---------------- */

const PROMPT_PHRASES = [
  "What's on your mind today?",
  "What should Atlas tackle first?",
  "Where do you want to start?",
];

const pickRandomPrompt = () => PROMPT_PHRASES[Math.floor(Math.random() * PROMPT_PHRASES.length)];

const GMAIL_LOGO = "/integrations/gmail.png";
const DRIVE_LOGO = "/integrations/drive.png";
const CALENDAR_LOGO = "/integrations/calendar.png";

const CONNECTED_INTEGRATIONS: IntegrationItem[] = [
  {
    id: "gmail-connected",
    name: "Gmail",
    description: "Your inbox is connected for email-aware automations.",
    accentClass: "",
    logo: <Image className={styles.integrationLogoImage} src={GMAIL_LOGO} alt="Gmail" width={32} height={32} unoptimized />,
    connectedLabel: "2023.pranav.chandak@ves.ac.in",
  },
];

const AVAILABLE_INTEGRATIONS: IntegrationItem[] = [
  {
    id: "gmail",
    name: "Gmail",
    description: "Add Gmail to route messages, reminders, and follow-ups.",
    accentClass: "",
    logo: <Image className={styles.integrationLogoImage} src={GMAIL_LOGO} alt="Gmail" width={32} height={32} unoptimized />,
  },
  {
    id: "drive",
    name: "Google Drive",
    description: "Sync Drive files so Atlas can reference docs instantly.",
    accentClass: "",
    logo: <Image className={styles.integrationLogoImage} src={DRIVE_LOGO} alt="Drive" width={32} height={32} unoptimized />,
  },
  {
    id: "calendar",
    name: "Google Calendar",
    description: "Bring your schedule in so Atlas can spot time blocks.",
    accentClass: "",
    logo: <Image className={styles.integrationLogoImage} src={CALENDAR_LOGO} alt="Calendar" width={32} height={32} unoptimized />,
  },
  {
    id: "notion",
    name: "Notion",
    description: "Connect Notion to keep task notes, specs, and checklists in sync.",
    accentClass: styles.integrationBadgeNotion,
    logo: <SiNotion />,
  },
  {
    id: "discord",
    name: "Discord",
    description: "Send updates to Discord when Atlas finishes work.",
    accentClass: styles.integrationBadgeDiscord,
    logo: <SiDiscord />,
  },
];

const DEFAULT_STARTUP_SCHEMA = `{\n  "task_id": "morning_routine",\n  "trigger": "on_boot",\n  "steps": [\n    { "action": "fetch_api", "url": "https://news.ycombinator.com" }\n  ]\n}`;
const DEFAULT_SKILL_SCHEMA = `{\n  "skill_id": "custom_skill",\n  "description": "What this skill does...",\n  "parameters": [],\n  "steps": []\n}`;

/* ---------------- PAGE ---------------- */

export default function Home() {
  const {
    status,
    messages,
    terminalLogs,
    isWorking,
    sendMessage: sendWebSocketMessage,
    stopGeneration,
    addTerminalLog,
  } = useAtlasWebSocket();

  const API_BASE = "http://localhost:8000/atlas";
  const isConnectionReady = status === "CONNECTED";

  const [activeView, setActiveView] = useState<SidebarView>("new-chat");
  const [promptPhrase, setPromptPhrase] = useState(PROMPT_PHRASES[0]);
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);
  const [isMockWorking, setIsMockWorking] = useState(false);

  const isCurrentlyWorking = isWorking || isMockWorking;

  const [browserProfiles, setBrowserProfiles] = useState<BrowserProfileItem[]>([]);
  const [savedDocuments, setSavedDocuments] = useState<DocumentItem[]>([]);
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);

  const [profileSearch, setProfileSearch] = useState("");
  const [messageText, setMessageText] = useState("");
  const [composerProfileId, setComposerProfileId] = useState("");

  const [expandedProfileId, setExpandedProfileId] = useState<string | null>(null);
  const [expandedSchemaId, setExpandedSchemaId] = useState<string | null>(null);

  // Dynamic Skills & Tasks State
  const [isAddingTask, setIsAddingTask] = useState(false);
  const [newTaskName, setNewTaskName] = useState("");
  const [newTaskSchema, setNewTaskSchema] = useState("");
  
  const [isAddingSkill, setIsAddingSkill] = useState(false);
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillSchema, setNewSkillSchema] = useState("");

  const docUploadRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  const [skillsList, setSkillsList] = useState<SchemaItem[]>([
    { id: "s1", name: "Fetch ECS (Sem 5)", action: () => runSkillDemo("ecs", "5"), schema: JSON.stringify(VESIT_RESULT_SKILL_SCHEMA, null, 2) },
    { id: "s2", name: "Fetch CMPN (Sem 4)", action: () => runSkillDemo("cmpn", "4"), schema: JSON.stringify(VESIT_RESULT_SKILL_SCHEMA, null, 2) },
    { id: "s3", name: "Fetch IT (Sem 5)", action: () => runSkillDemo("it", "5"), schema: JSON.stringify(VESIT_RESULT_SKILL_SCHEMA, null, 2) },
  ]);

  const [tasksList, setTasksList] = useState<SchemaItem[]>([
    { id: "t1", name: "Morning Routine", action: () => runStartupDemo(), schema: DEFAULT_STARTUP_SCHEMA },
  ]);

  const allMessages: ChatMessage[] = [...(messages as ChatMessage[]), ...localMessages];

  /* ---------------- EFFECTS ---------------- */

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, localMessages, isCurrentlyWorking]); // Fixed: exhaustive-deps

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalLogs]);

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const profileRes = await fetch(`${API_BASE}/profiles`);
        const profileJson = await profileRes.json();
        
        // Mock domains for profiles since they aren't stored in backend yet
        const mockDomainSets = [
          ["github.com", "google.com", "jira.atlassian.com"],
          ["aws.amazon.com", "vercel.com", "reddit.com"],
          ["linkedin.com", "twitter.com"]
        ];

        const enrichedProfiles = (profileJson.profiles || []).map((p: RawProfile, i: number) => ({
          ...p,
          domains: mockDomainSets[i % mockDomainSets.length]
        }));

        setBrowserProfiles(enrichedProfiles);

        // Auto-select first profile for composer
        if (enrichedProfiles.length > 0) {
          setComposerProfileId(enrichedProfiles[0].id);
        }
      } catch (err) {
        console.error(err);
      }

      setSavedDocuments([{ id: "doc-1", name: "resume.pdf", size: "245 KB" }]);
    };

    void loadInitialData();
  }, []);

  /* ---------------- FILTERS ---------------- */

  const filteredBrowserProfiles = useMemo(() => {
    const q = profileSearch.trim().toLowerCase();
    return q ? browserProfiles.filter((item) => item.name.toLowerCase().includes(q)) : browserProfiles;
  }, [browserProfiles, profileSearch]);

  /* ---------------- ACTIONS ---------------- */

  const startNewChat = () => {
    setActiveView("new-chat");
    setPromptPhrase(pickRandomPrompt());
    setMessageText("");
    setLocalMessages([]);
  };

  const sendMessage = () => {
    if (!isConnectionReady || !messageText.trim() || !composerProfileId) return;
    sendWebSocketMessage(messageText.trim());
    setMessageText("");
  };

  const createProfile = async () => {
    const name = prompt("Enter a name for the new browser profile:");
    if (!name) return;

    try {
      const res = await fetch(`${API_BASE}/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) return;

      const profileRes = await fetch(`${API_BASE}/profiles`);
      const json = await profileRes.json();
      const enrichedProfiles = (json.profiles || []).map((p: RawProfile) => ({
        ...p,
        domains: ["New Profile (No domains yet)"]
      }));
      setBrowserProfiles(enrichedProfiles);
      if (!composerProfileId && enrichedProfiles.length > 0) setComposerProfileId(enrichedProfiles[0].id);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDocUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;

    const newDocs = files.map((file) => ({
      id: `doc-${Date.now()}-${file.name}`,
      name: file.name,
      size: `${(file.size / 1024).toFixed(1)} KB`,
    }));

    setSavedDocuments((prev) => [...newDocs, ...prev]);
    e.target.value = "";
  };

  const saveNewTask = () => {
    if (!newTaskSchema.trim() || !newTaskName.trim()) return;
    setTasksList(prev => [...prev, { 
      id: `task-${Date.now()}`, 
      name: newTaskName.trim(), 
      schema: newTaskSchema,
      action: () => alert(`Mock Execution: ${newTaskName}`)
    }]);
    setIsAddingTask(false);
    setNewTaskSchema("");
    setNewTaskName("");
  };

  const saveNewSkill = () => {
    if (!newSkillSchema.trim() || !newSkillName.trim()) return;
    setSkillsList(prev => [...prev, { 
      id: `skill-${Date.now()}`, 
      name: newSkillName.trim(), 
      schema: newSkillSchema,
      action: () => alert(`Mock Execution: ${newSkillName}`)
    }]);
    setIsAddingSkill(false);
    setNewSkillSchema("");
    setNewSkillName("");
  };

  /* ---------------- DEMOS ---------------- */

  const runSkillDemo = async (dept: "ecs" | "it" | "cmpn", sem: "4" | "5") => {
    setIsTerminalOpen(true);
    setIsMockWorking(true);
    setLocalMessages((prev) => [...prev, { role: "user", content: `Execute skill: fetch_vesit_results for ${dept.toUpperCase()} Sem ${sem}` }]);

    const result = await executeVesitSkill(dept, sem, addTerminalLog!);

    setLocalMessages((prev) => [...prev, { role: "ai", content: result }]);
    setActiveView("new-chat");
    setIsMockWorking(false);
  };

  const runStartupDemo = async () => {
    setIsTerminalOpen(true);
    setIsMockWorking(true);
    setLocalMessages((prev) => [...prev, { role: "user", content: "Run morning routine." }]);

    const result = await runStartupRoutine(addTerminalLog!);

    setLocalMessages((prev) => [...prev, { role: "ai", content: result }]);
    setActiveView("new-chat");
    setIsMockWorking(false);
  };

  /* ---------------- UI ---------------- */

  return (
    <div className={`${styles.shell} ${isTerminalOpen ? styles.shellTerminalOpen : styles.shellTerminalCollapsed}`}>
      
      {/* SIDEBAR */}
      <aside className={styles.sidebar}>
        <div className={styles.sidebarTop}>
          <p className={styles.brand}>Atlas</p>
          <p className={styles.brandSub}>Autonomous Browser Agent</p>
        </div>

        <button type="button" className={`${styles.newChatButton} ${activeView === "new-chat" ? styles.newChatButtonActive : ""}`} onClick={startNewChat}>
          New Chat
        </button>

        <nav className={styles.navList}>
          <button className={`${styles.navItem} ${activeView === "browser-sessions" ? styles.navItemActive : ""}`} onClick={() => setActiveView("browser-sessions")}>Browser Profiles</button>
          <button className={`${styles.navItem} ${activeView === "saved-memory" ? styles.navItemActive : ""}`} onClick={() => setActiveView("saved-memory")}>Saved Documents</button>
          <button className={`${styles.navItem} ${activeView === "integrations" ? styles.navItemActive : ""}`} onClick={() => setActiveView("integrations")}>Integrations</button>
          <button className={`${styles.navItem} ${activeView === "startup-tasks" ? styles.navItemActive : ""}`} onClick={() => setActiveView("startup-tasks")}>Startup Tasks</button>
          <button className={`${styles.navItem} ${activeView === "skills" ? styles.navItemActive : ""}`} onClick={() => setActiveView("skills")}>Skills</button>
        </nav>
      </aside>

      {/* CENTER */}
      <section className={styles.centerPanel}>
        <div className={styles.statusBar}>
          <span className={`${styles.connectionBadge} ${isConnectionReady ? styles.connected : styles.notConnected}`}>
            {isConnectionReady ? "Connected" : "Not Connected"}
          </span>
        </div>

        {/* CHAT */}
        {activeView === "new-chat" && (
          <div className={styles.newChatStage}>
            <div className={`${styles.newChatContent} ${allMessages.length === 0 ? styles.newChatContentCentered : ""}`}>
              {allMessages.length === 0 ? (
                <p className={styles.promptPhrase}>{promptPhrase}</p>
              ) : (
                <div className={styles.chatStream}>
                  {allMessages.map((message, index) => (
                    <div key={index} className={`${styles.messageBubble} ${message.role === "user" ? styles.userBubble : styles.agentBubble}`}>
                      {message.role === "ai" ? <ReactMarkdown>{message.content}</ReactMarkdown> : message.content}
                    </div>
                  ))}

                  {isCurrentlyWorking && (
                    <div className={`${styles.messageBubble} ${styles.agentBubble} ${styles.thinkingBubble}`}>
                      <span className={styles.dot}>.</span>
                      <span className={styles.dot}>.</span>
                      <span className={styles.dot}>.</span>
                    </div>
                  )}

                  <div ref={chatEndRef} />
                </div>
              )}
            </div>

            <form className={styles.chatComposer} onSubmit={(e) => { e.preventDefault(); sendMessage(); }}>
              <input type="text" className={styles.composerInput} placeholder="Type a message" value={messageText} onChange={(e) => setMessageText(e.target.value)} disabled={isCurrentlyWorking} />

              <div className={styles.composerActions}>
                <select className={styles.profileSelectInline} value={composerProfileId} onChange={(e) => setComposerProfileId(e.target.value)} disabled={isCurrentlyWorking || browserProfiles.length === 0}>
                  {browserProfiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              {isCurrentlyWorking ? (
                <button type="button" className={styles.stopButton} onClick={() => { stopGeneration(); setIsMockWorking(false); }}>Stop</button>
              ) : (
                <button type="submit" className={styles.sendButton} disabled={!isConnectionReady || !messageText.trim() || !composerProfileId}>Send</button>
              )}
            </form>
          </div>
        )}

        {/* PROFILES */}
        {activeView === "browser-sessions" && (
          <div className={styles.workspacePanel}>
            <div className={styles.panelHeader}>
              <h1 className={styles.panelTitle}>Browser Profiles</h1>
              <p className={styles.panelSubtitle}>Manage isolated browser environments and view saved authentications.</p>
            </div>

            <div className={styles.tableCard}>
              <div className={styles.tableControls}>
                <input className={styles.searchInput} placeholder="Search profiles" value={profileSearch} onChange={(e) => setProfileSearch(e.target.value)} />
                <button className={styles.createButton} onClick={createProfile}>Create Profile</button>
              </div>

              <div className={styles.tableWrap}>
                {filteredBrowserProfiles.map((item) => (
                  <div key={item.id} className={styles.profileRowContainer}>
                    <div className={styles.tableRowProfiles} onClick={() => setExpandedProfileId(expandedProfileId === item.id ? null : item.id)}>
                      <p className={styles.cellPrimary}>{item.name}</p>
                      <p className={styles.cellMutedDropdown}>
                        {item.domains.length} saved sessions {expandedProfileId === item.id ? "▲" : "▼"}
                      </p>
                    </div>
                    {expandedProfileId === item.id && (
                      <div className={styles.profileDomainsList}>
                        <p className={styles.domainHeader}>Stored Authentications & Cookies:</p>
                        <ul>
                          {item.domains.map(d => <li key={d}>{d}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
                {!filteredBrowserProfiles.length && <div className={styles.emptyState}>No profiles found.</div>}
              </div>
            </div>
          </div>
        )}

        {/* DOCS */}
        {activeView === "saved-memory" && (
          <div className={styles.workspacePanel}>
            <div className={styles.panelHeader}>
              <h1 className={styles.panelTitle}>Saved Documents</h1>
              <p className={styles.panelSubtitle}>Upload PDFs and documents for semantic retrieval and context during execution.</p>
            </div>

            <div className={styles.tableCard}>
              <div className={styles.tableControls}>
                <input ref={docUploadRef} type="file" multiple style={{ display: "none" }} onChange={handleDocUpload} />
                <button className={styles.createButton} onClick={() => docUploadRef.current?.click()}>Upload Document</button>
              </div>

              <div className={styles.tableWrap}>
                {savedDocuments.map((doc) => (
                  <div key={doc.id} className={styles.documentRow}>
                    <p className={styles.documentName}>{doc.name}</p>
                    <p className={styles.documentSize}>{doc.size}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* INTEGRATIONS */}
        {activeView === "integrations" && (
          <div className={styles.workspacePanel}>
            <div className={styles.panelHeader}>
              <h1 className={styles.panelTitle}>Integrations</h1>
              <p className={styles.panelSubtitle}>Connect Atlas to your external services and daily workflows.</p>
            </div>

            <div className={styles.integrationSection}>
              <div className={styles.integrationBlock}>
                <h2 className={styles.integrationSectionTitle}>Connected</h2>
                <div className={styles.integrationGridSingle}>
                  {CONNECTED_INTEGRATIONS.map((integration) => (
                    <article className={styles.integrationCard} key={integration.id}>
                      <div className={`${styles.integrationLogo} ${integration.accentClass}`}>
                        {integration.logo}
                      </div>
                      <div className={styles.integrationCardBody}>
                        <div className={styles.integrationCardTitleRow}>
                          <div>
                            <h2 className={styles.integrationCardTitle}>{integration.name}</h2>
                            <p className={styles.integrationCardText}>{integration.description}</p>
                          </div>
                          <span className={styles.integrationConnectedPill}>{integration.connectedLabel}</span>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              </div>

              <div className={styles.integrationBlock}>
                <h2 className={styles.integrationSectionTitle}>Add More</h2>
                <div className={styles.integrationGrid}>
                  {AVAILABLE_INTEGRATIONS.map((integration) => (
                    <article className={styles.integrationCard} key={integration.id}>
                      <div className={`${styles.integrationLogo} ${integration.accentClass}`}>
                        {integration.logo}
                      </div>
                      <div className={styles.integrationCardBody}>
                        <h2 className={styles.integrationCardTitle}>{integration.name}</h2>
                        <p className={styles.integrationCardText}>{integration.description}</p>
                      </div>
                      <button type="button" className={styles.integrationAddButton}>+</button>
                    </article>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STARTUP TASKS */}
        {activeView === "startup-tasks" && (
          <div className={styles.workspacePanel}>
            <div className={styles.panelHeader}>
              <h1 className={styles.panelTitle}>Startup Tasks</h1>
              <p className={styles.panelSubtitle}>Automated routines that run efficiently on system boot without requiring full agent reasoning. Provide a valid JSON schema to create a new task.</p>
            </div>

            <div className={styles.tableCard} style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
                <p style={{ color: "#888", margin: 0 }}>Trigger predefined startup routines.</p>
                <button className={styles.createButton} onClick={() => { setIsAddingTask(!isAddingTask); setNewTaskSchema(DEFAULT_STARTUP_SCHEMA); setNewTaskName(""); }}>
                  {isAddingTask ? "Cancel" : "Add Task"}
                </button>
              </div>

              {isAddingTask && (
                <div className={styles.schemaInputContainer}>
                  <input 
                    className={styles.composerInput} 
                    style={{ marginBottom: "10px", background: "#000", border: "1px solid #222" }} 
                    placeholder="Startup Task Name (e.g., Fetch News)" 
                    value={newTaskName} 
                    onChange={(e) => setNewTaskName(e.target.value)} 
                  />
                  <textarea className={styles.schemaTextarea} value={newTaskSchema} onChange={(e) => setNewTaskSchema(e.target.value)} />
                  <button className={styles.createButton} style={{ alignSelf: "flex-end", marginTop: "10px" }} onClick={saveNewTask} disabled={!newTaskName.trim() || !newTaskSchema.trim()}>
                    Save Task Schema
                  </button>
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {tasksList.map(task => (
                  <div key={task.id} className={styles.schemaItemBox}>
                    <div className={styles.schemaItemHeader}>
                      <button className={styles.ghostButton} onClick={task.action} style={{flex: 1, textAlign: "left"}}>▶ {task.name}</button>
                      <button className={styles.iconButton} onClick={() => setExpandedSchemaId(expandedSchemaId === task.id ? null : task.id)}>
                        {expandedSchemaId === task.id ? "▲" : "▼"}
                      </button>
                    </div>
                    {expandedSchemaId === task.id && (
                      <pre className={styles.schemaCodeBlock}><code>{task.schema}</code></pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* SKILLS */}
        {activeView === "skills" && (
          <div className={styles.workspacePanel}>
            <div className={styles.panelHeader}>
              <h1 className={styles.panelTitle}>Skill Library</h1>
              <p className={styles.panelSubtitle}>Execute deterministic JSON workflows instantly via the Macro Engine. Import a new skill by providing its structured JSON schema.</p>
            </div>

            <div className={styles.tableCard} style={{ padding: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
                 <p style={{ color: "#888", margin: 0 }}>Run imported skills directly from the library.</p>
                 <button className={styles.createButton} onClick={() => { setIsAddingSkill(!isAddingSkill); setNewSkillSchema(DEFAULT_SKILL_SCHEMA); setNewSkillName(""); }}>
                   {isAddingSkill ? "Cancel" : "Add Skill"}
                 </button>
              </div>

              {isAddingSkill && (
                <div className={styles.schemaInputContainer}>
                  <input 
                    className={styles.composerInput} 
                    style={{ marginBottom: "10px", background: "#000", border: "1px solid #222" }} 
                    placeholder="Skill Name (e.g., Fetch Results)" 
                    value={newSkillName} 
                    onChange={(e) => setNewSkillName(e.target.value)} 
                  />
                  <textarea className={styles.schemaTextarea} value={newSkillSchema} onChange={(e) => setNewSkillSchema(e.target.value)} />
                  <button className={styles.createButton} style={{ alignSelf: "flex-end", marginTop: "10px" }} onClick={saveNewSkill} disabled={!newSkillName.trim() || !newSkillSchema.trim()}>
                    Save Skill Schema
                  </button>
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {skillsList.map(skill => (
                  <div key={skill.id} className={styles.schemaItemBox}>
                    <div className={styles.schemaItemHeader}>
                      <button className={styles.ghostButton} onClick={skill.action} style={{flex: 1, textAlign: "left"}}>▶ {skill.name}</button>
                      <button className={styles.iconButton} onClick={() => setExpandedSchemaId(expandedSchemaId === skill.id ? null : skill.id)}>
                        {expandedSchemaId === skill.id ? "▲" : "▼"}
                      </button>
                    </div>
                    {expandedSchemaId === skill.id && (
                      <pre className={styles.schemaCodeBlock}><code>{skill.schema}</code></pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

      </section>

      {/* TERMINAL */}
      <aside className={`${styles.rightPanel} ${isTerminalOpen ? styles.rightPanelOpen : styles.rightPanelCollapsed}`}>
        <button className={styles.terminalRailButton} onClick={() => setIsTerminalOpen((v) => !v)}>
          {isTerminalOpen ? ">" : "<"}
        </button>

        {isTerminalOpen && (
          <div className={styles.terminalContent}>
            <p className={styles.terminalTitle}>Terminal</p>
            <div className={styles.terminalBody}>
              {terminalLogs.length === 0 ? (
                <span className={styles.terminalPlaceholder}>Waiting for logs...</span>
              ) : (
                terminalLogs.map((log, i) => <div key={i}>{log}</div>)
              )}
              <div ref={terminalEndRef} />
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}