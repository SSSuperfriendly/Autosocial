import type { ReactNode } from "react";

export type TabKey = "tracking" | "discovery" | "pool" | "trash" | "drafts" | "settings";

const items: Array<{ key: TabKey; label: string }> = [
  { key: "tracking", label: "工作台" },
  { key: "pool", label: "导师池" },
  { key: "discovery", label: "发现导师" },
  { key: "drafts", label: "写信" },
  { key: "trash", label: "回收站" },
  { key: "settings", label: "设置" }
];

type Props = {
  activeTab: TabKey;
  onTabChange: (key: TabKey) => void;
  children: ReactNode;
};

export function Layout({ activeTab, onTabChange, children }: Props) {
  return (
    <div className="app-shell top-shell">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand brand-minimal">
            <div>
              <h1>AutoSocial</h1>
              <p className="brand-description">让每一次联系，都有下一步。</p>
            </div>
          </div>
        </div>

        <nav className="top-nav" aria-label="主导航">
          {items.map((item) => (
            <button
              key={item.key}
              className={item.key === activeTab ? "top-nav-item active" : "top-nav-item"}
              onClick={() => onTabChange(item.key)}
              type="button"
              aria-current={item.key === activeTab ? "page" : undefined}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="page-content top-content">
        <div className="page-frame">{children}</div>
      </main>
    </div>
  );
}
