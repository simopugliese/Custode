import {
  House,
  BookOpen,
  GraduationCap,
  ListTodo,
  ShoppingCart,
  Wallet,
  Repeat,
  Zap,
  Settings,
  Moon,
  Plus,
  Check,
  ArrowRight,
  ArrowDown,
  Search,
  PenLine,
  Pencil,
  RotateCcw,
  Send,
  Lightbulb,
  Receipt,
  Download,
  CalendarClock,
  Info,
  ClipboardCheck,
  CheckCircle,
  type LucideIcon,
} from 'lucide-react';

/** kebab-case name (matching the design mock's data-lucide attributes) -> component */
export const ICONS = {
  house: House,
  'book-open': BookOpen,
  'graduation-cap': GraduationCap,
  'list-todo': ListTodo,
  'shopping-cart': ShoppingCart,
  wallet: Wallet,
  repeat: Repeat,
  zap: Zap,
  settings: Settings,
  moon: Moon,
  plus: Plus,
  check: Check,
  'arrow-right': ArrowRight,
  'arrow-down': ArrowDown,
  search: Search,
  'pen-line': PenLine,
  pencil: Pencil,
  'rotate-ccw': RotateCcw,
  send: Send,
  lightbulb: Lightbulb,
  receipt: Receipt,
  download: Download,
  'calendar-clock': CalendarClock,
  info: Info,
  'clipboard-check': ClipboardCheck,
  'check-circle': CheckCircle,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  const Cmp = ICONS[name];
  return <Cmp size={size} />;
}
