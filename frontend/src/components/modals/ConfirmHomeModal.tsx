export function ConfirmHomeModal({ onConfirm, onClose }: { onConfirm: () => void; onClose: () => void }) {
  return (
    <div className="ov open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mh"><h2>Вернуться в главное меню?</h2></div>
        <p style={{ margin: 0, padding: "6px 22px 14px" }}>Вы закрываете последнюю выбранную карточку: связи исчезнут, и откроется обзор разделов.</p>
        <div style={{ padding: "0 22px 18px" }}>
          <button onClick={onConfirm}>Да, вернуться</button>{" "}
          <button className="alt" onClick={onClose}>Остаться</button>
        </div>
      </div>
    </div>
  );
}
