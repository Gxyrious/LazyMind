import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n';
import type { SlotRevision } from '@/modules/chat/store/workflowPanel';
import { DocumentArtifactEditor } from './DocumentArtifactEditor';
import { SlotEditingContext, type SlotFooterAction } from './slotEditingContext';

const api = vi.hoisted(() => ({ listDocumentProviders: vi.fn(), publishDocument: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock('@/modules/chat/utils/request', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/chat/utils/request')>(),
  WorkflowSessionApi: () => api,
}));
vi.mock('antd', async (importOriginal) => ({
  ...await importOriginal<typeof import('antd')>(), Modal: { confirm },
}));

vi.mock('./MarkdownArtifactEditor', () => ({
  MarkdownArtifactEditor: ({ markdown }: { markdown: string }) => <article>{markdown}</article>,
}));
vi.mock('./WriterIRControl', () => ({ WriterIRControl: () => null }));
vi.mock('./ArtifactRewriteDialog', () => ({ ArtifactRewriteDialog: () => null }));
vi.mock('./useDocumentCopy', () => ({ useDocumentCopy: () => {} }));
vi.mock('./WriterDownloadFormat', () => ({
  WriterDownloadFormatDialog: () => null,
  writerDownloadFilename: () => '',
  writerDownloadCacheKey: () => '',
}));

afterEach(() => cleanup());

describe('document artifact display', () => {
  it('shows the failed publication stage returned by the backend', async () => {
    await i18n.changeLanguage('zh-CN');
    api.listDocumentProviders.mockResolvedValue({ data: { data: { providers: [{ id: 'feishu', capabilities: ['create', 'replace'] }] } } });
    api.publishDocument.mockRejectedValue({ response: { data: { data: { code: 'DOCUMENT_CONVERSION_FAILED' } } } });
    const registerFooterAction = vi.fn((_key: string, _action: SlotFooterAction | null) => () => {});
    const slot = {
      artifact_id: 'artifact-test', slot_id: 'draft_document', revision: 1,
      artifact_value: { text: '# Completed story' },
      document: { representation: 'markdown', editable: true, capabilities: ['save', 'publish_document'] },
    } as SlotRevision;
    render(<SlotEditingContext.Provider value={{ setEditing: vi.fn(), registerFlush: () => () => {}, registerFooterAction }}>
      <DocumentArtifactEditor slot={slot} sessionId='session-test' />
    </SlotEditingContext.Provider>);
    await waitFor(() => expect(registerFooterAction).toHaveBeenCalledWith(
      expect.any(String), expect.objectContaining({ icon: 'write-back', disabled: false }),
    ));
    const action = registerFooterAction.mock.calls.at(-1)![1]!;
    act(() => action.onClick());
    await act(async () => { await confirm.mock.calls.at(-1)![0].onOk(); });
    expect(await screen.findByRole('alert')).toHaveTextContent('飞书 文档转换阶段失败，尚未写入');
    expect(api.publishDocument).toHaveBeenCalledTimes(1);
  });
  it.each([['zh-CN', '下载'], ['en-US', 'Download']])(
    'loads the completed Markdown and registers a translated download label in %s',
    async (language, label) => {
      await i18n.changeLanguage(language);
      const registerFooterAction = vi.fn(() => () => {});
      const slot = {
        artifact_id: 'artifact-test', slot_id: 'draft_document', revision: 1,
        artifact_value: { text: '# Completed story\n\nThe first paragraph.' },
        document: { representation: 'markdown', editable: true, capabilities: ['save', 'convert_document'] },
      } as SlotRevision;
      render(
        <SlotEditingContext.Provider value={{
          setEditing: vi.fn(), registerFlush: () => () => {}, registerFooterAction,
        }}>
          <DocumentArtifactEditor slot={slot} sessionId='session-test' />
        </SlotEditingContext.Provider>,
      );
      expect(await screen.findByRole('article')).toHaveTextContent('The first paragraph.');
      await waitFor(() => expect(registerFooterAction).toHaveBeenCalledWith(
        expect.any(String), expect.objectContaining({ icon: 'download', label }),
      ));
    },
  );
});
