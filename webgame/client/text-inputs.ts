import type { ShellController, ShellSnapshot } from "./shell-controller.js";

interface MountedInput {
  readonly nodeId: string;
  readonly input: HTMLInputElement;
}

function label(nodeId: string): string {
  if (nodeId === "dark_account.dark_name") {
    return "Dark Name";
  }
  if (nodeId === "dark_account.password") {
    return "Password";
  }
  return "Boneyard search name";
}

export class TextInputOverlay {
  readonly #root: HTMLElement;
  readonly #canvas: HTMLCanvasElement;
  readonly #controller: ShellController;
  #mounted: MountedInput[] = [];
  #snapshot: ShellSnapshot | null = null;

  public constructor(root: HTMLElement, canvas: HTMLCanvasElement, controller: ShellController) {
    this.#root = root;
    this.#canvas = canvas;
    this.#controller = controller;
    window.addEventListener("resize", () => {
      this.#position();
    });
  }

  public update(snapshot: ShellSnapshot): void {
    this.#snapshot = snapshot;
    const wanted = snapshot.focusNodes.filter((node) => node.textEntry);
    const wantedIds = new Set(wanted.map((node) => node.id));
    for (const mounted of this.#mounted) {
      if (!wantedIds.has(mounted.nodeId)) {
        mounted.input.remove();
      }
    }
    this.#mounted = this.#mounted.filter((mounted) => wantedIds.has(mounted.nodeId));
    for (const node of wanted) {
      let mounted = this.#mounted.find((candidate) => candidate.nodeId === node.id);
      if (mounted === undefined) {
        const input = document.createElement("input");
        input.type = node.id.endsWith(".password") ? "password" : "text";
        input.autocomplete = "off";
        input.spellcheck = false;
        input.setAttribute("aria-label", label(node.id));
        input.dataset.actionId = node.id;
        input.addEventListener("input", () => {
          this.#controller.setTextValue(node.id, input.value);
        });
        input.addEventListener("focus", () => {
          input.dataset.active = "true";
        });
        input.addEventListener("blur", () => {
          delete input.dataset.active;
        });
        this.#root.append(input);
        mounted = { nodeId: node.id, input };
        this.#mounted.push(mounted);
      }
      const value = snapshot.values[node.id];
      if (typeof value === "string" && mounted.input.value !== value) {
        mounted.input.value = value;
      }
    }
    this.#position();
    const focused = this.#mounted.find((mounted) => mounted.nodeId === snapshot.focusId)?.input;
    if (focused !== undefined && document.activeElement !== focused) {
      focused.focus({ preventScroll: true });
    }
  }

  #position(): void {
    if (this.#snapshot === null) {
      return;
    }
    const canvas = this.#canvas.getBoundingClientRect();
    for (const mounted of this.#mounted) {
      const node = this.#snapshot.focusNodes.find((candidate) => candidate.id === mounted.nodeId);
      if (node === undefined) {
        continue;
      }
      const [left, top, right, bottom] = node.nativeRect;
      Object.assign(mounted.input.style, {
        left: `${left / 1600 * canvas.width}px`,
        top: `${top / 900 * canvas.height}px`,
        width: `${(right - left) / 1600 * canvas.width}px`,
        height: `${(bottom - top) / 900 * canvas.height}px`,
        fontSize: `${Math.max(12, 19 / 900 * canvas.height)}px`,
      });
    }
  }
}
