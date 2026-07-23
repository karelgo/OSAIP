// The dataset metadata block both creation panels share: name/description plus the
// CP-1 classification axes and CP-2 purpose fields (react-hook-form + zod).
import { Field, Input } from "@osaip/ui";
import type { UseFormReturn } from "react-hook-form";
import { NativeSelect } from "../../lib/NativeSelect";
import {
  BBN_LEVELS,
  CLASSIFICATIONS,
  CONFIDENTIALITY_LEVELS,
  type DatasetMetaValues,
} from "./lib";

export function DatasetMetaFields({
  form,
  cp2Hint,
}: {
  form: UseFormReturn<DatasetMetaValues>;
  /** Hint under legal basis / purpose codes (e.g. inheritance note for registers). */
  cp2Hint?: string;
}) {
  const { errors } = form.formState;
  return (
    <>
      <Field
        label="Name"
        error={errors.name?.message}
        hint="Permanent identifier; used in URLs and storage paths."
      >
        <Input
          data-testid="dataset-name-input"
          className="font-mono"
          placeholder="customer-orders"
          {...form.register("name")}
        />
      </Field>
      <Field label="Description" error={errors.description?.message}>
        <Input placeholder="What does this data describe?" {...form.register("description")} />
      </Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Classification" error={errors.classification?.message}>
          <NativeSelect {...form.register("classification")}>
            {CLASSIFICATIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="BBN level" error={errors.bbn_level?.message}>
          <NativeSelect {...form.register("bbn_level")}>
            <option value="">not set</option>
            {BBN_LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Confidentiality" error={errors.confidentiality?.message}>
          <NativeSelect {...form.register("confidentiality")}>
            <option value="">not set</option>
            {CONFIDENTIALITY_LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <Field label="Legal basis" error={errors.legal_basis?.message} hint={cp2Hint}>
        <Input
          data-testid="dataset-legal-basis-input"
          placeholder="e.g. Art 6(1)(e) AVG"
          {...form.register("legal_basis")}
        />
      </Field>
      <Field
        label="Purpose codes"
        error={errors.purpose_codes?.message}
        hint={cp2Hint ? `Comma-separated. ${cp2Hint}` : "Comma-separated, e.g. demo, analytics"}
      >
        <Input
          data-testid="dataset-purpose-input"
          placeholder="demo, analytics"
          {...form.register("purpose_codes")}
        />
      </Field>
    </>
  );
}
