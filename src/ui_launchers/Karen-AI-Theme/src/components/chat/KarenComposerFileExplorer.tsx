"use client";

import { useId, useState } from "react";
import { FolderOpen } from "lucide-react";
import { FileExplorerInventoryHost } from "@/components/plugins/FileExplorerInventoryHost";
import { PluginHost } from "@/components/plugins/PluginHost";

import { MAX_DRAFT_ATTACHMENTS, type DraftAttachment } from "./copilotkit/useKarenPersistedDraft";

export function KarenComposerFileExplorer({
  pluginId, onAttach, disabled = false, existingAttachments = [],
}: {
  pluginId: string;
  onAttach?: (references: DraftAttachment[]) => void;
  disabled?: boolean;
  existingAttachments?: readonly DraftAttachment[];
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return <div className="min-w-0 max-w-full px-3 pt-2">
    <button type="button" disabled={disabled} aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => setOpen(value => !value)}
      className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-input px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring">
      <FolderOpen aria-hidden="true" className="h-4 w-4" /> Browse files
    </button>
    {open && !disabled && <section id={id} aria-label="Conversation file browser"
      className="mt-2 max-h-72 min-w-0 overflow-auto rounded-lg border border-border/60 p-2">
      <p className="px-2 pb-2 text-xs text-muted-foreground">
        Select files, then choose Attach selected files to save references in your draft.
        File contents are not read, and attached messages cannot be sent yet.
      </p>
      <p role="status" className="px-2 pb-2 text-xs text-muted-foreground">{Math.max(0, MAX_DRAFT_ATTACHMENTS - existingAttachments.length)} additional file references available.</p>
      <FileExplorerInventoryHost mode="selection" onAttach={onAttach} existingAttachments={existingAttachments}>
        {componentProps => <PluginHost pluginId={pluginId} componentProps={componentProps} />}
      </FileExplorerInventoryHost>
    </section>}
  </div>;
}
