import { metabaseCharts } from '../config/metabaseCharts'
import './Dashboard.css'

function ChartCard({
  title,
  description,
  url,
}: {
  title: string
  description: string
  url: string
}) {
  return (
    <article className="chart-card">
      <header className="chart-card__header">
        <h2>{title}</h2>
        <p>{description}</p>
      </header>
      {url ? (
        <iframe
          className="chart-card__frame"
          title={title}
          src={url}
          loading="lazy"
          allow="fullscreen"
        />
      ) : (
        <div className="chart-card__empty">
          Chart URL not configured yet. Run <code>metabase/setup_metabase.py</code>.
        </div>
      )}
    </article>
  )
}

export default function Dashboard() {
  return (
    <div className="dashboard">
      <header className="dashboard__hero">
        <p className="dashboard__eyebrow">HM Land Registry · Price Paid Data</p>
        <h1>England &amp; Wales property sales, 2026 YTD</h1>
        <p className="dashboard__lede">
          Live charts from PostgreSQL via Metabase. Each panel is a public Metabase
          question embedded in this React app.
        </p>
      </header>

      <section className="dashboard__grid">
        {metabaseCharts.map((chart) => (
          <ChartCard
            key={chart.id}
            title={chart.title}
            description={chart.description}
            url={chart.url}
          />
        ))}
      </section>

      <footer className="dashboard__footer">
        Contains HM Land Registry data © Crown copyright and database right 2026.
        This information is licensed under the Open Government Licence v3.0.
      </footer>
    </div>
  )
}
