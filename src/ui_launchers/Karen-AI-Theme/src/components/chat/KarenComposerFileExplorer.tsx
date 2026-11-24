"use client";

import { useId, useState } from "react";
import { FolderOpen } from "lucide-react";
import { FileExplorerInventoryHost } from "@/components/plugins/FileExplorerInventoryHost";
import { PluginHost } from "@/components/plugins/PluginHost";

export function KarenComposerFileExplorer({ pluginId }: { pluginId: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return <div className="min-w-0 max-w-full px-3 pt-2">
    <button type="button" aria-expanded={open} aria-controls={open ? id : undefined}
      onClick={() => setOpen(value => !value)}
      className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-input px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring">
      <FolderOpen aria-hidden="true" className="h-4 w-4" /> Browse files
    </button>
    {open && <section id={id} aria-label="Conversation file browser"
      className="mt-2 max-h-72 min-w-0 overflow-auto rounded-lg border border-border/60 p-2">
      <p className="px-2 pb-2 text-xs text-muted-foreground">
        Browse and select file metadata. Selection is not attached to your message,
        does not read file contents, and is cleared when this browser closes.
      </p>
      <FileExplorerInventoryHost mode="selection">
        {componentProps => <PluginHost pluginId={pluginId} componentProps={componentProps} />}
      </FileExplorerInventoryHost>
    </section>}
  </div>;
}
