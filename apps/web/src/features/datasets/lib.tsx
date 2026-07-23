// Shared vocabulary for the datasets feature: CP-1/CP-2 label constants, value
// formatting, and the classification badge cluster used on lists and headers.
import { Badge } from "@osaip/ui";
import { z } from "zod";

export const CLASSIFICATIONS = ["none", "persoonsgegevens", "bijzonder", "bsn"] as const;
export const BBN_LEVELS = ["bbn1", "bbn2", "bbn3"] as const;
export const CONFIDENTIALITY_LEVELS = ["intern", "vertrouwelijk", "geheim"] as const;

export type Classification = (typeof CLASSIFICATIONS)[number];
export type BbnLevel = (typeof BBN_LEVELS)[number];
export type Confidentiality = (typeof CONFIDENTIALITY_LEVELS)[number];

// Dataset metadata fields shared by the upload and register panels. Selects use ""
// for "not set" (native <option> values are strings); mapped to null for the API.
export const datasetMetaSchema = z.object({
  name: z
    .string()
    .regex(
      /^[a-z][a-z0-9_-]{1,63}$/,
      "Lowercase letters, digits, - and _; must start with a letter",
    ),
  description: z.string().max(10_000),
  classification: z.enum(["none", "persoonsgegevens", "bijzonder", "bsn"]),
  bbn_level: z.enum(["", "bbn1", "bbn2", "bbn3"]),
  confidentiality: z.enum(["", "intern", "vertrouwelijk", "geheim"]),
  legal_basis: z.string().max(500),
  purpose_codes: z.string(),
});

export type DatasetMetaValues = z.infer<typeof datasetMetaSchema>;

export function parsePurposeCodes(raw: string): string[] {
  return raw
    .split(",")
    .map((code) => code.trim())
    .filter(Boolean);
}

/** Map form values to the DatasetCreate metadata fields (CP-2 empties → null → inherit). */
export function toDatasetMeta(values: DatasetMetaValues) {
  const purposes = parsePurposeCodes(values.purpose_codes);
  return {
    name: values.name,
    description: values.description,
    classification: values.classification,
    bbn_level: values.bbn_level === "" ? null : values.bbn_level,
    confidentiality: values.confidentiality === "" ? null : values.confidentiality,
    legal_basis: values.legal_basis.trim() === "" ? null : values.legal_basis.trim(),
    purpose_codes: purposes.length > 0 ? purposes : null,
  };
}

/** Derive a valid dataset name from a filename or table reference. */
export function slugifyName(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^[^a-z]+/, "")
    .replace(/-+$/, "")
    .slice(0, 64);
}

/** Render an arbitrary sample/preview cell value. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** "~12,345" for estimates (§6.3: honesty about estimates), "—" when unknown. */
export function formatRowCount(rowCount: number | null, rowCountKind: string | null): string {
  if (rowCount === null) return "—";
  const formatted = rowCount.toLocaleString();
  return rowCountKind === "estimate" ? `~${formatted}` : formatted;
}

const CLASSIFICATION_VARIANT = {
  persoonsgegevens: "warning",
  bijzonder: "danger",
  bsn: "danger",
} as const;

/** CP-1/BBN/confidentiality badge cluster — distinct muted styles per axis. */
export function ClassificationBadges({
  classification,
  bbnLevel,
  confidentiality,
}: {
  classification: string;
  bbnLevel: string | null;
  confidentiality: string | null;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {classification !== "none" && (
        <Badge
          variant={
            CLASSIFICATION_VARIANT[classification as keyof typeof CLASSIFICATION_VARIANT] ??
            "neutral"
          }
        >
          {classification}
        </Badge>
      )}
      {bbnLevel ? <Badge variant="info">{bbnLevel}</Badge> : null}
      {confidentiality ? <Badge variant="neutral">{confidentiality}</Badge> : null}
    </span>
  );
}
