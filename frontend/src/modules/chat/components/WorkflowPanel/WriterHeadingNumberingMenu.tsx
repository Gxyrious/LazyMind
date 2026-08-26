import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  WriterHeadingNumberingMode,
  WriterNumberingUpdate,
  WriterOrderedHeadingNumberingStyle,
} from '@/modules/chat/utils/request';

interface WriterHeadingNumberingMenuProps {
  x: number;
  y: number;
  targetId: string;
  mode: WriterHeadingNumberingMode;
  orderedStyle: WriterOrderedHeadingNumberingStyle;
  restart: boolean;
  disabled?: boolean;
  onApply: (update: WriterNumberingUpdate) => void;
  onClose: () => void;
}

export function WriterHeadingNumberingMenu({
  x,
  y,
  targetId,
  mode,
  orderedStyle,
  restart,
  disabled = false,
  onApply,
  onClose,
}: WriterHeadingNumberingMenuProps) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape') return;
      const target = event.target;
      if (
        event.type !== 'keydown'
        && target instanceof Element
        && rootRef.current?.contains(target)
      ) return;
      onClose();
    };
    document.addEventListener('mousedown', close, true);
    document.addEventListener('keydown', close);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', close, true);
      document.removeEventListener('keydown', close);
      window.removeEventListener('resize', close);
    };
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      className='writer-numbering-menu'
      role='dialog'
      aria-label={t('chat.writerIR.numberingSettings')}
      style={{
        left: Math.min(x, globalThis.innerWidth - 300),
        top: Math.min(y, globalThis.innerHeight - 210),
      }}
    >
      <label>
        <span>{t('chat.writerIR.headingOrder')}</span>
        <select
          value={mode}
          disabled={disabled}
          onChange={(event) => onApply({
            type: 'heading',
            target_id: targetId,
            mode: event.target.value as WriterHeadingNumberingMode,
          })}
        >
          <option value='ordered'>{t('chat.writerIR.orderedHeading')}</option>
          <option value='unordered'>{t('chat.writerIR.unorderedHeading')}</option>
        </select>
      </label>
      {mode === 'ordered' && (
        <label>
          <span>{t('chat.writerIR.numberingStyle')}</span>
          <select
            value={orderedStyle}
            disabled={disabled}
            onChange={(event) => onApply({
              type: 'ordered_style',
              ordered_style: event.target.value as WriterOrderedHeadingNumberingStyle,
            })}
          >
            <option value='hierarchical'>1. / 1.1 / 1.1.1</option>
            <option value='chinese'>一、 / （一） / 1.</option>
            <option value='parenthesized'>(1) / (a) / (i)</option>
          </select>
        </label>
      )}
      {mode === 'ordered' && (
        <label>
          <span>{t('chat.writerIR.numberingContinuation')}</span>
          <select
            value={restart ? 'restart' : 'continue'}
            disabled={disabled}
            onChange={(event) => onApply({
              type: 'heading',
              target_id: targetId,
              restart: event.target.value === 'restart',
            })}
          >
            <option value='continue'>{t('chat.writerIR.continueNumbering')}</option>
            <option value='restart'>{t('chat.writerIR.restartNumbering')}</option>
          </select>
        </label>
      )}
    </div>
  );
}
