// The Studio left-rail IA (spec §6.2, LOCKED). Groups and order are the contract;
// unbuilt destinations render phase-labeled starting points (§6.3(9)).
import {
  BarChart3,
  Bot,
  Boxes,
  Database,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Library,
  MessageSquare,
  Monitor,
  NotebookPen,
  Rocket,
  ScrollText,
  Settings,
  Sparkles,
  Timer,
  Wrench,
} from "lucide-react";

export interface RailItem {
  label: string;
  path: string; // relative to /p/$key
  icon: typeof Database;
  phase?: number; // set ⇒ stub until that phase ships
}

export interface RailGroup {
  label: string | null;
  items: RailItem[];
}

export const RAIL_GROUPS: RailGroup[] = [
  {
    label: null,
    items: [{ label: "Flow", path: ".", icon: GitBranch }],
  },
  {
    label: "Data",
    items: [
      { label: "Datasets", path: "datasets", icon: Database },
      { label: "Notebooks", path: "notebooks", icon: NotebookPen, phase: 9 },
    ],
  },
  {
    label: "Grounding",
    items: [
      { label: "Knowledge", path: "knowledge", icon: Library, phase: 4 },
      { label: "Semantic", path: "semantic", icon: Boxes, phase: 5 },
    ],
  },
  {
    label: "Agents",
    items: [
      { label: "Agents", path: "agents", icon: Bot, phase: 6 },
      { label: "Prompts & Tools", path: "prompts", icon: Wrench, phase: 3 },
      { label: "Evals", path: "evals", icon: FlaskConical, phase: 7 },
      { label: "Traces", path: "traces", icon: ScrollText, phase: 6 },
    ],
  },
  {
    label: "Chat",
    items: [
      { label: "Answers apps", path: "answers", icon: MessageSquare, phase: 4 },
      { label: "Hub", path: "hub-admin", icon: Sparkles, phase: 7 },
    ],
  },
  {
    label: null,
    items: [{ label: "ML Lab", path: "ml", icon: BarChart3, phase: 10 }],
  },
  {
    label: "Automation",
    items: [
      { label: "Scenarios", path: "scenarios", icon: Timer, phase: 8 },
      { label: "Jobs", path: "jobs", icon: Monitor },
    ],
  },
  {
    label: "Deploy",
    items: [
      { label: "Deployments", path: "deployments", icon: Rocket, phase: 7 },
      { label: "Monitoring", path: "monitoring", icon: Monitor, phase: 7 },
    ],
  },
  {
    label: null,
    items: [
      { label: "Dashboards", path: "dashboards", icon: LayoutDashboard, phase: 12 },
      { label: "Settings", path: "settings", icon: Settings },
    ],
  },
];
