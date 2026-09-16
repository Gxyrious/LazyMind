import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { MDXEditorMethods, MDXEditorProps } from '@mdxeditor/editor';
import i18n from '@/i18n';
import { SlotRenderer } from './SlotComponents';
import type { SlotRevision } from '@/modules/chat/store/workflowPanel';

const capture = vi.hoisted(() => ({ change: undefined as MDXEditorProps['onChange'], editor: null as MDXEditorMethods | null }));
const api = vi.hoisted(() => ({ getSlotItemVersions: vi.fn(), rollbackSlotItem: vi.fn(), getSlots: vi.fn(), saveDocumentArtifact: vi.fn() }));
vi.mock('@mdxeditor/editor', async () => {
  const actual = await vi.importActual<typeof import('@mdxeditor/editor')>('@mdxeditor/editor');
  const React = await import('react');
  return { ...actual, MDXEditor: React.forwardRef<MDXEditorMethods, MDXEditorProps>((props, ref) => {
    capture.change = props.onChange;
    return <actual.MDXEditor {...props} ref={editor => { capture.editor = editor; if (typeof ref === 'function') ref(editor); else if (ref) ref.current = editor; }} />;
  }) };
});
vi.mock('@/modules/chat/utils/request', async original => ({
  ...await original<typeof import('@/modules/chat/utils/request')>(), WorkflowSessionApi: () => api,
}));
vi.mock('./FilePreviewDrawer', () => ({ FilePreviewDrawer: () => null }));
vi.mock('./useDocumentCopy', () => ({ useDocumentCopy: () => {} }));
vi.mock('./ArtifactRewriteDialog', () => ({ ArtifactRewriteDialog: () => null, ArtifactRewriteInlineDiff: () => null }));
vi.mock('./useWriterProviderAvailability', () => ({ useWriterProviderAvailability: () => ({ states: {} }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

it.each(['markdown', 'ir', 'ir-to-markdown'] as const)('preserves edits and resumes real %s editing after rollback', async mode => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  await i18n.changeLanguage('zh-CN');
  const document = (title: string) => ({ document_id: 'history-document', stage: 'draft', title,
    blocks: [{ node_id: 'p', type: 'paragraph', content: 'Existing paragraph.' }] });
  const slot = (revision: number): SlotRevision => {
    const markdown = mode === 'markdown' || (mode === 'ir-to-markdown' && revision === 1);
    return { artifact_id: `history-${revision}`, slot_id: 'flat_draft_document', revision, draft_version: revision + 1,
      selected: true, change_source: 'ai', artifact_value: { data: markdown ? `# Version ${revision}\n\nExisting paragraph.\n` : document(`Version ${revision}`) },
      document: { representation: markdown ? 'markdown' : 'ir', editable: true, capabilities: ['save'] },
    } as SlotRevision;
  };
  api.getSlotItemVersions.mockResolvedValue({ data: { data: { versions: [1, 3].map(revision => ({
    revision, change_source: 'ai', selected: revision === 3, created_at: '2026-09-16T00:00:00Z', content_snapshot: slot(revision).artifact_value,
  })) } } });
  api.rollbackSlotItem.mockResolvedValue({ data: { data: { revision: 1 } } });
  api.getSlots.mockResolvedValue({ data: { data: { slots: [slot(1)] } } });
  api.saveDocumentArtifact.mockImplementation(async (_id, body) => ({ data: { ok: true, result: {
    artifact_id: `local-${body.base_revision}`, revision: body.base_revision + 1, draft_version: 1, value: body.value,
  } } }));
  const view = render(<SlotRenderer slot={slot(3)} sessionId='real-history' slotId='flat_draft_document' revisionCount={3} />);
  await screen.findByRole('button', { name: '版本历史', exact: true });
  const typeTitle = async (text: string, markdown: boolean) => {
    if (markdown) {
      await act(async () => capture.editor!.setMarkdown(`# ${text}\n\nExisting paragraph.`));
      await act(async () => capture.change?.(capture.editor!.getMarkdown(), false));
    } else {
      const heading = view.container.querySelector('h1')!;
      heading.textContent = text;
      fireEvent.input(heading);
    }
  };
  await typeTitle('Saved before rollback', mode === 'markdown');
  fireEvent.click(screen.getByRole('button', { name: '版本历史', exact: true }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getAllByRole('option').at(-1)!);
  fireEvent.click(within(dialog).getByRole('button', { name: /应用.*1/ }));
  await waitFor(() => expect(view.container.querySelector('h1')).toHaveTextContent('Version 1'));
  expect(api.saveDocumentArtifact.mock.invocationCallOrder[0]).toBeLessThan(api.rollbackSlotItem.mock.invocationCallOrder[0]);
  expect(JSON.stringify(api.saveDocumentArtifact.mock.calls[0][1].value)).toContain('Saved before rollback');
  await typeTitle('Edited after rollback', mode !== 'ir');
  await waitFor(() => expect(api.saveDocumentArtifact).toHaveBeenLastCalledWith('history-1', expect.objectContaining({
    base_revision: 1, base_draft_version: 2,
  }), expect.anything()), { timeout: 2500 });
  expect(JSON.stringify(api.saveDocumentArtifact.mock.calls.at(-1)![1].value)).toContain('Edited after rollback');
  expect(view.container.querySelector('[role="alert"]')).toBeNull();
});
