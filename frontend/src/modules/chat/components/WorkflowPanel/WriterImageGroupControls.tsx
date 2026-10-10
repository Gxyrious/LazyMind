import { useState } from 'react';

export function WriterImageGroupControls({ count, layout, readOnly, onLayout, onMove }: {
  count: number; layout?: 'sliding' | 'vertical'; readOnly?: boolean;
  onLayout: (layout: 'sliding' | 'vertical') => void;
  onMove: (index: number, direction: -1 | 1) => void;
}) {
  const [ordering, setOrdering] = useState(false);
  if (readOnly) return null;
  return <div className='writer-image-group-controls' contentEditable={false} onMouseDown={event => event.preventDefault()}>
    <button type='button' onClick={() => onLayout(layout === 'sliding' ? 'vertical' : 'sliding')}>
      {layout === 'sliding' ? '恢复纵向排列' : '设为滑动图组'}
    </button>
    {layout === 'sliding' && <button type='button' onClick={() => setOrdering(value => !value)}>调整图片顺序</button>}
    {ordering && layout === 'sliding' && <div className='writer-image-group-order' role='group' aria-label='调整图片顺序'>
      {Array.from({ length: count }, (_, index) => <div key={index}>
        <span>图片 {index + 1}</span>
        <button type='button' disabled={index === 0} aria-label={`图片 ${index + 1} 向前移动`} onClick={() => onMove(index, -1)}>向前</button>
        <button type='button' disabled={index === count - 1} aria-label={`图片 ${index + 1} 向后移动`} onClick={() => onMove(index, 1)}>向后</button>
      </div>)}
    </div>}
  </div>;
}
