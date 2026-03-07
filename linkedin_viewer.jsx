import { useState, useMemo, useCallback } from "react";

const SORT_OPTIONS = [
  { value: "index_desc", label: "Saved (newest)" },
  { value: "index_asc", label: "Saved (oldest)" },
  { value: "links_desc", label: "Most links" },
  { value: "author_asc", label: "Author A→Z" },
];

function parseDate(raw) {
  if (!raw) return null;
  const d = new Date(raw);
  return isNaN(d) ? null : d;
}

function LinkChip({ link }) {
  const domain = (() => {
    try { return new URL(link.url).hostname.replace("www.", ""); } catch { return link.url.slice(0, 30); }
  })();
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      title={link.url}
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        background: "#0f1923", border: "1px solid #1e3a5f",
        borderRadius: 4, padding: "3px 8px", fontSize: 11,
        color: "#5ba4f5", textDecoration: "none", fontFamily: "monospace",
        transition: "all .15s", whiteSpace: "nowrap", maxWidth: 260,
        overflow: "hidden", textOverflow: "ellipsis",
      }}
      onMouseEnter={e => { e.target.style.borderColor = "#5ba4f5"; e.target.style.background = "#0a2540"; }}
      onMouseLeave={e => { e.target.style.borderColor = "#1e3a5f"; e.target.style.background = "#0f1923"; }}
    >
      <span style={{ opacity: .6, fontSize: 10 }}>↗</span>
      {link.text || domain}
    </a>
  );
}

function PostCard({ post }) {
  const [expanded, setExpanded] = useState(false);
  const text = post.text || "";
  const preview = text.slice(0, 200);

  return (
    <div style={{
      background: "#0d1b2a", border: "1px solid #1a2e44",
      borderRadius: 10, padding: "18px 20px", marginBottom: 12,
      transition: "border-color .2s",
    }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "#2a5298"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "#1a2e44"}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <span style={{ fontWeight: 700, color: "#e8f0fe", fontSize: 14 }}>{post.author || "Unknown"}</span>
          {post.dateRaw && (
            <span style={{ marginLeft: 10, color: "#4a7ab5", fontSize: 11, fontFamily: "monospace" }}>
              {post.dateRaw.length > 20 ? new Date(post.dateRaw).toLocaleDateString() : post.dateRaw}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {post.links?.length > 0 && (
            <span style={{ background: "#0a2540", border: "1px solid #1e3a5f", borderRadius: 20, padding: "2px 8px", fontSize: 10, color: "#5ba4f5" }}>
              {post.links.length} link{post.links.length !== 1 ? "s" : ""}
            </span>
          )}
          {post.postUrl && (
            <a href={post.postUrl} target="_blank" rel="noopener noreferrer"
              style={{ color: "#4a7ab5", fontSize: 11, textDecoration: "none" }}>
              View post ↗
            </a>
          )}
        </div>
      </div>

      {/* Article title */}
      {post.articleTitle && (
        <div style={{ color: "#93c5fd", fontSize: 13, fontStyle: "italic", marginBottom: 6 }}>
          📄 {post.articleTitle}
        </div>
      )}

      {/* Text */}
      {text && (
        <p style={{ color: "#8ba8c7", fontSize: 13, lineHeight: 1.6, margin: "0 0 10px", whiteSpace: "pre-wrap" }}>
          {expanded ? text : preview}
          {text.length > 200 && (
            <button onClick={() => setExpanded(!expanded)}
              style={{ background: "none", border: "none", color: "#5ba4f5", cursor: "pointer", fontSize: 12, marginLeft: 4 }}>
              {expanded ? "less" : "...more"}
            </button>
          )}
        </p>
      )}

      {/* Links */}
      {post.links?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
          {post.links.map((l, i) => <LinkChip key={i} link={l} />)}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [posts, setPosts] = useState([]);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("index_desc");
  const [filterLinks, setFilterLinks] = useState(false);
  const [dragging, setDragging] = useState(false);

  const loadFile = useCallback((file) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target.result);
        setPosts(Array.isArray(data) ? data : []);
      } catch {
        alert("Couldn't parse JSON — make sure you're loading the file from the scraper.");
      }
    };
    reader.readAsText(file);
  }, []);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) loadFile(file);
  }, [loadFile]);

  const filtered = useMemo(() => {
    let out = [...posts];
    if (filterLinks) out = out.filter(p => p.links?.length > 0);
    if (search.trim()) {
      const q = search.toLowerCase();
      out = out.filter(p =>
        (p.text || "").toLowerCase().includes(q) ||
        (p.author || "").toLowerCase().includes(q) ||
        (p.articleTitle || "").toLowerCase().includes(q) ||
        p.links?.some(l => l.text?.toLowerCase().includes(q) || l.url?.toLowerCase().includes(q))
      );
    }
    if (sortBy === "index_desc") out.sort((a, b) => b.index - a.index);
    else if (sortBy === "index_asc") out.sort((a, b) => a.index - b.index);
    else if (sortBy === "links_desc") out.sort((a, b) => (b.links?.length || 0) - (a.links?.length || 0));
    else if (sortBy === "author_asc") out.sort((a, b) => (a.author || "").localeCompare(b.author || ""));
    return out;
  }, [posts, search, sortBy, filterLinks]);

  return (
    <div style={{
      minHeight: "100vh", background: "#060e1a",
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      color: "#e8f0fe",
    }}>
      {/* Header */}
      <div style={{ borderBottom: "1px solid #1a2e44", padding: "20px 32px", display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, letterSpacing: "-0.5px", color: "#5ba4f5" }}>
            LI Saved Posts
          </h1>
          <p style={{ margin: 0, fontSize: 11, color: "#4a5568", marginTop: 2 }}>
            {posts.length > 0 ? `${posts.length} posts loaded · ${filtered.length} shown` : "Load your scraped JSON to get started"}
          </p>
        </div>
      </div>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: "24px 20px" }}>

        {/* Drop zone */}
        {posts.length === 0 ? (
          <div>
            {/* Instructions */}
            <div style={{ background: "#0d1b2a", border: "1px solid #1a2e44", borderRadius: 10, padding: 20, marginBottom: 20 }}>
              <p style={{ margin: "0 0 10px", color: "#5ba4f5", fontSize: 12, fontWeight: 700 }}>STEP 1 — RUN THE SCRAPER</p>
              <ol style={{ margin: 0, paddingLeft: 18, color: "#8ba8c7", fontSize: 12, lineHeight: 2 }}>
                <li>Go to <a href="https://www.linkedin.com/my-items/saved-posts/" target="_blank" rel="noopener noreferrer" style={{ color: "#5ba4f5" }}>linkedin.com/my-items/saved-posts/</a></li>
                <li>Open DevTools → Console (F12 / Cmd+Option+I)</li>
                <li>Paste the contents of <code style={{ color: "#93c5fd" }}>linkedin_scraper.js</code> and hit Enter</li>
                <li>Wait for it to scroll + download the JSON file</li>
              </ol>
              <p style={{ margin: "12px 0 0", color: "#5ba4f5", fontSize: 12, fontWeight: 700 }}>STEP 2 — LOAD THE JSON BELOW</p>
            </div>

            <div
              onDrop={onDrop}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onClick={() => document.getElementById("fileInput").click()}
              style={{
                border: `2px dashed ${dragging ? "#5ba4f5" : "#1e3a5f"}`,
                borderRadius: 12, padding: "60px 20px", textAlign: "center",
                cursor: "pointer", transition: "all .2s",
                background: dragging ? "#0a2540" : "transparent",
              }}
            >
              <div style={{ fontSize: 36, marginBottom: 12 }}>📂</div>
              <p style={{ color: "#4a7ab5", margin: 0 }}>Drop your JSON here or click to browse</p>
              <input id="fileInput" type="file" accept=".json" style={{ display: "none" }}
                onChange={e => e.target.files[0] && loadFile(e.target.files[0])} />
            </div>
          </div>
        ) : (
          <>
            {/* Controls */}
            <div style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search posts, authors, links..."
                style={{
                  flex: 1, minWidth: 200, background: "#0d1b2a", border: "1px solid #1e3a5f",
                  borderRadius: 6, padding: "8px 12px", color: "#e8f0fe",
                  fontFamily: "inherit", fontSize: 12, outline: "none",
                }}
              />
              <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                style={{
                  background: "#0d1b2a", border: "1px solid #1e3a5f", borderRadius: 6,
                  padding: "8px 12px", color: "#e8f0fe", fontFamily: "inherit", fontSize: 12,
                }}>
                {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button onClick={() => setFilterLinks(!filterLinks)}
                style={{
                  background: filterLinks ? "#0a2540" : "transparent",
                  border: `1px solid ${filterLinks ? "#5ba4f5" : "#1e3a5f"}`,
                  borderRadius: 6, padding: "8px 12px", color: filterLinks ? "#5ba4f5" : "#4a7ab5",
                  cursor: "pointer", fontFamily: "inherit", fontSize: 12,
                }}>
                {filterLinks ? "✓" : ""} Has links only
              </button>
              <button onClick={() => { setPosts([]); }}
                style={{
                  background: "transparent", border: "1px solid #3a1a1a", borderRadius: 6,
                  padding: "8px 12px", color: "#7a4a4a", cursor: "pointer", fontFamily: "inherit", fontSize: 12,
                }}>
                Clear
              </button>
            </div>

            {/* Posts */}
            {filtered.length === 0 ? (
              <p style={{ color: "#4a7ab5", textAlign: "center", marginTop: 60 }}>No posts match your filters.</p>
            ) : (
              filtered.map((p, i) => <PostCard key={i} post={p} />)
            )}
          </>
        )}
      </div>
    </div>
  );
}