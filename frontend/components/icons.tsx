// Small inline stroke icons (no icon library needed).
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
function Svg({ size = 18, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {children}
    </svg>
  );
}

export const SidebarIcon = (p: P) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="3" />
    <path d="M9 4v16" />
  </Svg>
);
export const PlusIcon = (p: P) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);
export const ChatsIcon = (p: P) => (
  <Svg {...p}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
  </Svg>
);
export const ArrowUpIcon = (p: P) => (
  <Svg {...p} strokeWidth={2.25}>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </Svg>
);
export const StopIcon = (p: P) => (
  <Svg {...p}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
  </Svg>
);
export const SlidersIcon = (p: P) => (
  <Svg {...p}>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </Svg>
);
export const ChevronDownIcon = (p: P) => (
  <Svg {...p}>
    <path d="m6 9 6 6 6-6" />
  </Svg>
);
export const DotsIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="5" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="19" cy="12" r="1" fill="currentColor" />
  </Svg>
);
export const SettingsIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
  </Svg>
);
export const SunIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
);
export const MoonIcon = (p: P) => (
  <Svg {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
  </Svg>
);
export const LogoutIcon = (p: P) => (
  <Svg {...p}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
  </Svg>
);
export const FileIcon = (p: P) => (
  <Svg {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
    <path d="M14 3v5h5" />
  </Svg>
);
export const UploadIcon = (p: P) => (
  <Svg {...p}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
  </Svg>
);
export const CloseIcon = (p: P) => (
  <Svg {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Svg>
);
export const CheckIcon = (p: P) => (
  <Svg {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Svg>
);
export const CopyIcon = (p: P) => (
  <Svg {...p}>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </Svg>
);
export const LockIcon = (p: P) => (
  <Svg {...p}>
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </Svg>
);
export const InfoIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 16v-4M12 8h.01" />
  </Svg>
);
export const StarIcon = (p: P) => (
  <Svg {...p}>
    <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9Z" />
  </Svg>
);
export const PencilIcon = (p: P) => (
  <Svg {...p}>
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z" />
  </Svg>
);
export const TrashIcon = (p: P) => (
  <Svg {...p}>
    <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
  </Svg>
);
export const BackIcon = (p: P) => (
  <Svg {...p}>
    <path d="M19 12H5M12 19l-7-7 7-7" />
  </Svg>
);

/** SmartRoute mark: one input splitting into three routes. */
export function RouteMark({ size = 22, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
        <path d="M5 12c5 0 6-7 13-7" />
        <path d="M5 12h13" />
        <path d="M5 12c5 0 6 7 13 7" />
      </g>
      <circle cx="4.5" cy="12" r="2.6" fill="currentColor" />
      <circle cx="19.5" cy="5" r="2" fill="currentColor" />
      <circle cx="19.5" cy="12" r="2" fill="currentColor" />
      <circle cx="19.5" cy="19" r="2" fill="currentColor" />
    </svg>
  );
}
