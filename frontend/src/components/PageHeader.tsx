export function PageHeader({ title, children, actions }: { title: string; children?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <header className="page-header">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <h1>{title}</h1>
        {actions}
      </div>
      {children ? <p>{children}</p> : null}
    </header>
  );
}
