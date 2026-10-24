export default function NotFound() {
  return (
    <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
      <div className="notice">
        <h2>Такой страницы нет</h2>
        <p>Возможно, событие уже прошло или ссылка устарела. <a href="/digest">Вернуться к подборке</a></p>
      </div>
    </main>
  );
}
