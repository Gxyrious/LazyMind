import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MentionEditor from "./MentionEditor";

type ScrollablePrototype = typeof HTMLElement.prototype & {
  scrollTo?: (...args: unknown[]) => void;
};

const scrollablePrototype = HTMLElement.prototype as ScrollablePrototype;
const originalScrollTo = scrollablePrototype.scrollTo;

const mocks = vi.hoisted(() => ({
  listSkillAssetsPage: vi.fn(),
  listToolAssetsPage: vi.fn(),
  listDatasets: vi.fn(),
  listPrompts: vi.fn(),
  listConversations: vi.fn(),
  axiosGet: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/modules/memory/skillApi", () => ({
  listSkillAssetsPage: mocks.listSkillAssetsPage,
}));

vi.mock("@/modules/memory/toolApi", () => ({
  listToolAssetsPage: mocks.listToolAssetsPage,
}));

vi.mock("@/components/request", () => ({
  BASE_URL: "",
  axiosInstance: { get: mocks.axiosGet },
}));

vi.mock("@/modules/chat/utils/request", () => ({
  ChatServiceApi: () => ({
    conversationServiceListConversations: mocks.listConversations,
  }),
  KnowledgeBaseServiceApi: () => ({
    datasetServiceListDatasets: mocks.listDatasets,
  }),
  PromptServiceApi: () => ({
    listPrompts: mocks.listPrompts,
  }),
}));

describe("MentionEditor", () => {
  beforeEach(() => {
    Object.defineProperty(scrollablePrototype, "scrollTo", {
      configurable: true,
      value: vi.fn(),
    });

    mocks.listSkillAssetsPage.mockReset();
    mocks.listToolAssetsPage.mockReset();
    mocks.listDatasets.mockReset();
    mocks.listPrompts.mockReset();
    mocks.listConversations.mockReset();
    mocks.axiosGet.mockReset();

    mocks.listSkillAssetsPage.mockResolvedValue({ records: [] });
    mocks.listToolAssetsPage.mockResolvedValue({ records: [] });
    mocks.listDatasets.mockResolvedValue({ data: { datasets: [] } });
    mocks.listPrompts.mockResolvedValue({ data: { prompts: [] } });
    mocks.listConversations.mockResolvedValue({ data: { conversations: [] } });
    mocks.axiosGet.mockResolvedValue({ data: { workflows: [] } });
  });

  afterEach(() => {
    window.getSelection()?.removeAllRanges();
    if (originalScrollTo) {
      Object.defineProperty(scrollablePrototype, "scrollTo", {
        configurable: true,
        value: originalScrollTo,
      });
    } else {
      Reflect.deleteProperty(scrollablePrototype, "scrollTo");
    }
    vi.restoreAllMocks();
  });

  it("reloads skills after a previously cached empty list", async () => {
    render(
      <MentionEditor
        value=""
        placeholder="message"
        onChange={vi.fn()}
        onMentionsChange={vi.fn()}
        onPaste={vi.fn()}
        onSend={vi.fn()}
        onCompositionChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(mocks.listSkillAssetsPage).toHaveBeenCalledTimes(1);
    });

    mocks.listSkillAssetsPage.mockResolvedValue({
      records: [
        {
          id: "skill-new",
          name: "新增技能",
          description: "刚刚添加的技能",
        },
      ],
    });

    const editor = screen.getByRole("textbox");
    editor.textContent = "@skill:";
    const range = document.createRange();
    const textNode = editor.firstChild;
    if (!textNode) {
      throw new Error("Mention editor did not create a text node");
    }
    range.setStart(textNode, textNode.textContent?.length || 0);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);

    expect(await screen.findByRole("option", { name: "新增技能" })).toBeInTheDocument();
    expect(mocks.listSkillAssetsPage).toHaveBeenCalledTimes(2);
  });

  it("reloads workflows so newly published workflows are shown", async () => {
    render(
      <MentionEditor
        value=""
        placeholder="message"
        onChange={vi.fn()}
        onMentionsChange={vi.fn()}
        onPaste={vi.fn()}
        onSend={vi.fn()}
        onCompositionChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(mocks.axiosGet).toHaveBeenCalledTimes(1));
    mocks.axiosGet.mockResolvedValue({
      data: {
        workflows: [{
          workflow_ref: "user:user-1:ppt-workflow-copy",
          workflow_id: "ppt-workflow-copy",
          name: "AI PPT 规划 副本",
          description: "",
        }],
      },
    });

    const editor = screen.getByRole("textbox");
    editor.textContent = "@workflow:";
    const textNode = editor.firstChild;
    if (!textNode) throw new Error("Mention editor did not create a text node");
    const range = document.createRange();
    range.setStart(textNode, textNode.textContent?.length || 0);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);

    expect(await screen.findByRole("option", { name: "AI PPT 规划 副本" })).toBeInTheDocument();
    expect(mocks.axiosGet).toHaveBeenCalledTimes(2);
  });

  it("resets the mention menu scroll when the query changes", async () => {
    mocks.listSkillAssetsPage.mockResolvedValue({
      records: [{ id: "skill-find", name: "find-skill-skillhub" }],
    });

    render(
      <MentionEditor
        value=""
        placeholder="message"
        onChange={vi.fn()}
        onMentionsChange={vi.fn()}
        onPaste={vi.fn()}
        onSend={vi.fn()}
        onCompositionChange={vi.fn()}
      />,
    );

    const editor = screen.getByRole("textbox");
    editor.textContent = "@find";
    let textNode = editor.firstChild;
    if (!textNode) throw new Error("Mention editor did not create a text node");
    let range = document.createRange();
    range.setStart(textNode, textNode.textContent?.length || 0);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);

    expect(await screen.findByRole("option", { name: "find-skill-skillhub" })).toBeInTheDocument();
    await waitFor(() => expect(scrollablePrototype.scrollTo).toHaveBeenCalledWith({ top: 0 }));
    vi.mocked(scrollablePrototype.scrollTo).mockClear();

    editor.textContent = "@find-skill";
    textNode = editor.firstChild;
    if (!textNode) throw new Error("Mention editor did not create a text node");
    range = document.createRange();
    range.setStart(textNode, textNode.textContent?.length || 0);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);

    await waitFor(() => expect(scrollablePrototype.scrollTo).toHaveBeenCalledWith({ top: 0 }));
  });

  it("renders each mention group as soon as that group finishes loading", async () => {
    mocks.listSkillAssetsPage.mockResolvedValue({
      records: [{ id: "skill-find", name: "find-skill-skillhub" }],
    });
    mocks.listConversations.mockReturnValue(new Promise(() => undefined));

    render(
      <MentionEditor
        value=""
        placeholder="message"
        onChange={vi.fn()}
        onMentionsChange={vi.fn()}
        onPaste={vi.fn()}
        onSend={vi.fn()}
        onCompositionChange={vi.fn()}
      />,
    );

    const editor = screen.getByRole("textbox");
    editor.textContent = "@find";
    const textNode = editor.firstChild;
    if (!textNode) throw new Error("Mention editor did not create a text node");
    const range = document.createRange();
    range.setStart(textNode, textNode.textContent?.length || 0);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);

    expect(await screen.findByRole("option", { name: "find-skill-skillhub" })).toBeInTheDocument();
  });

describe("mention text boundaries", () => {
  it.each([
    ["workflow", "Research Workflow"],
    ["skill", "Search Skill"],
    ["knowledge_base", "Project Knowledge"],
    ["tool", "Local Tool"],
    ["conversation", "Earlier Chat"],
  ])("separates %s labels from text sent to the backend", (type, name) => {
    const onChange = vi.fn();
    const onMentionsChange = vi.fn();
    render(<MentionEditor value="" placeholder="message" onChange={onChange} onMentionsChange={onMentionsChange}
      onPaste={vi.fn()} onSend={vi.fn()} onCompositionChange={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    const chip = document.createElement("span");
    chip.contentEditable = "false";
    chip.dataset.mentionId = "fixture";
    chip.dataset.mentionType = type;
    chip.dataset.resourceId = "fixture-resource";
    chip.dataset.displayName = name;
    chip.textContent = name;
    editor.append(chip, document.createTextNode("\u200bhttps://example.test/document"));
    fireEvent.input(editor);
    expect(onChange).toHaveBeenLastCalledWith(name + " https://example.test/document");
    expect(onMentionsChange).toHaveBeenLastCalledWith([expect.objectContaining({
      type, resource_id: "fixture-resource", display_name: name, start: 0, end: name.length,
    })]);
  });
  it("preserves ordinary text without mention chips", () => {
    const onChange = vi.fn();
    render(<MentionEditor value="" placeholder="message" onChange={onChange} onMentionsChange={vi.fn()}
      onPaste={vi.fn()} onSend={vi.fn()} onCompositionChange={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    const plain = "Please read obsidian://open?vault=Fixture&file=Note";
    editor.textContent = plain;
    fireEvent.input(editor);
    expect(onChange).toHaveBeenLastCalledWith(plain);
  });
  it.each(["", "\u200b", " ", "\n"])("keeps an Obsidian link separate after a chip with separator %j", separator => {
    const onChange = vi.fn();
    const onMentionsChange = vi.fn();
    render(<MentionEditor value="" placeholder="message" onChange={onChange} onMentionsChange={onMentionsChange}
      onPaste={vi.fn()} onSend={vi.fn()} onCompositionChange={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    const locator = "obsidian://open?vault=Fixture%20Vault&file=Note";
    editor.innerHTML = '<span contenteditable="false" data-mention-id="workflow" data-mention-type="workflow" data-resource-id="writer-workflow" data-display-name="AI Writer">AI Writer</span>';
    editor.append(document.createTextNode(separator + locator));
    fireEvent.input(editor);
    const expected = "AI Writer" + (separator === "\n" ? "\n" : " ") + locator;
    expect(onChange).toHaveBeenLastCalledWith(expected);
    expect(onMentionsChange).toHaveBeenLastCalledWith([expect.objectContaining({ start: 0, end: 9, display_name: "AI Writer" })]);
  });
  it("keeps offsets correct for adjacent chips and nested text", () => {
    const onChange = vi.fn();
    const onMentionsChange = vi.fn();
    render(<MentionEditor value="" placeholder="message" onChange={onChange} onMentionsChange={onMentionsChange}
      onPaste={vi.fn()} onSend={vi.fn()} onCompositionChange={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    editor.innerHTML = '<span data-mention-id="one" data-mention-type="workflow" data-resource-id="one" data-display-name="AI Writer">AI Writer</span><span data-mention-id="two" data-mention-type="skill" data-resource-id="two" data-display-name="Skill">Skill</span><b>obsidian://open?vault=Fixture&amp;file=Note</b>';
    fireEvent.input(editor);
    expect(onChange).toHaveBeenLastCalledWith("AI Writer Skill obsidian://open?vault=Fixture&file=Note");
    const mentions = onMentionsChange.mock.calls[onMentionsChange.mock.calls.length - 1][0];
    expect(mentions.map(({ start, end }: { start: number; end: number }) => [start, end])).toEqual([[0, 9], [10, 15]]);
  });
});

});
