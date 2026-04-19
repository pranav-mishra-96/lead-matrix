import type { ProfileEvent, TierEvent } from "../types/chat";

interface Props {
  profile: ProfileEvent | null;
  tier: TierEvent | null;
}

// ---------------------------------------------------------------------------
// Small helpers for rendering field rows
// ---------------------------------------------------------------------------
interface FieldRowProps {
  label: string;
  value: string | number | null | undefined;
  formatter?: (v: string | number) => string;
  badge?: string;
}

function FieldRow({ label, value, formatter, badge }: FieldRowProps) {
  const hasValue = value !== null && value !== undefined && value !== "";
  const display = hasValue
    ? formatter
      ? formatter(value as string | number)
      : String(value)
    : "not collected";

  return (
    <div className={`field ${hasValue ? "field--filled" : "field--empty"}`}>
      <span
        className={`field__indicator ${hasValue ? "field__indicator--on" : ""}`}
        aria-hidden
      />
      <div className="field__body">
        <div className="field__label">{label}</div>
        <div className="field__value">
          {display}
          {hasValue && badge && <span className="field__badge">{badge}</span>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Map internal enum values to human-readable labels
// ---------------------------------------------------------------------------
const SEGMENT_LABELS: Record<string, string> = {
  industrial: "Industrial",
  commercial: "Commercial",
};

const CONTRACT_LABELS: Record<string, string> = {
  expiring_soon: "Expiring < 6 months",
  expiring_within_year: "Expiring < 12 months",
  month_to_month: "Month-to-month",
  fixed_term: "Fixed term",
  no_provider: "No current provider",
};

const TIER_META: Record<
  string,
  { label: string; color: string; description: string }
> = {
  tier_1: {
    label: "Tier 1",
    color: "tier-badge--success",
    description: "Instant priority",
  },
  tier_2: {
    label: "Tier 2",
    color: "tier-badge--warning",
    description: "Follow-up",
  },
  tier_3: {
    label: "Tier 3",
    color: "tier-badge--neutral",
    description: "Nurture",
  },
  unqualified: {
    label: "Unqualified",
    color: "tier-badge--muted",
    description: "No matching rule",
  },
};

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export function DebugPanel({ profile, tier }: Props) {
  const tierMeta = tier ? TIER_META[tier.tier] : null;

  return (
    <aside className="debug-panel" aria-label="Agent state">
      <div className="debug-panel__section">
        <h2 className="debug-panel__heading">Lead Profile</h2>

        <FieldRow
          label="Business Segment"
          value={
            profile?.business_segment
              ? SEGMENT_LABELS[profile.business_segment] ?? profile.business_segment
              : null
          }
        />
        <FieldRow
          label="Annual Usage"
          value={profile?.annual_usage_mwh ?? null}
          formatter={(v) => `${v} MWh/yr`}
          badge={profile?.usage_was_estimated ? "estimated" : undefined}
        />
        <FieldRow
          label="Contract Status"
          value={
            profile?.contract_status
              ? CONTRACT_LABELS[profile.contract_status] ?? profile.contract_status
              : null
          }
        />
        <FieldRow
          label="Building Age"
          value={profile?.building_age_years ?? null}
          formatter={(v) => `${v} years`}
        />
        <FieldRow
          label="Square Footage"
          value={profile?.square_footage ?? null}
          formatter={(v) => `${Number(v).toLocaleString()} sq ft`}
        />
      </div>

      <div className="debug-panel__section">
        <h2 className="debug-panel__heading">Qualification</h2>

        {tierMeta ? (
          <div className="tier-result">
            <div className={`tier-badge ${tierMeta.color}`}>
              {tierMeta.label}
            </div>
            <div className="tier-result__description">
              {tierMeta.description}
            </div>
            <div className="tier-result__rule">
              Rule: <code>{tier!.matched_rule}</code>
            </div>
          </div>
        ) : (
          <div className="tier-pending">
            <span className="tier-pending__dot" />
            Awaiting sufficient information…
          </div>
        )}
      </div>
    </aside>
  );
}