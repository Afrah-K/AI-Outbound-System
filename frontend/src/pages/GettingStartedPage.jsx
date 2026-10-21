import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CheckIcon, ArrowRightIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'

function Example({ children }) {
  return <code className="rounded-md bg-gray-100 px-1.5 py-0.5 text-[13px] text-gray-800">{children}</code>
}

/**
 * One worked example, start to finish, in plain words. Each step ticks itself
 * off from real data, so this doubles as a setup checklist.
 */
export default function GettingStartedPage() {
  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: async () => (await api.system.status()).data,
  })
  const { data: sequences } = useQuery({
    queryKey: ['sequences'],
    queryFn: async () => (await api.sequences.list()).data,
  })

  const counts = status?.counts || {}
  const sequenceCount = sequences?.total ?? sequences?.sequences?.length ?? 0

  const steps = [
    {
      title: 'Connect your Gmail',
      text: 'Go to Inboxes and click Add Inbox to sign in with Google. Add two inboxes if you can - they send each other friendly emails every day ("warmup") so your real emails don\'t end up in spam.',
      done: counts.active_inboxes > 0,
      progress: counts.active_inboxes ? `${counts.active_inboxes} connected` : null,
      to: '/inboxes',
      button: 'Open Inboxes',
    },
    {
      title: 'Find businesses to email',
      text: (
        <>
          Open Scrapers and pick the <strong>Awwwards</strong> tab. Choose <Example>Web Design</Example> and{' '}
          <Example>United States</Example>, then click <strong>Run scraper</strong>. You'll get a list of design studios
          with their websites.
        </>
      ),
      done: counts.companies > 0,
      progress: counts.companies ? `${counts.companies} companies found` : null,
      to: '/scrapers',
      button: 'Open Scrapers',
    },
    {
      title: 'Find their email addresses',
      text: (
        <>
          When the list appears, click <strong>Find emails</strong>. The app visits each website and picks out a contact
          email like <Example>hello@studio.com</Example>. Everyone it finds is saved in Prospects.
        </>
      ),
      done: counts.people > 0,
      progress: counts.people ? `${counts.people} prospects` : null,
      to: '/enricher',
      button: 'Open Enricher',
    },
    {
      title: 'Write your email',
      text: (
        <>
          Open Sequences and write a short email, plus one or two follow-ups. Use <Example>{'{{first_name|there}}'}</Example>{' '}
          and <Example>{'{{company_name}}'}</Example> and each person gets their own name filled in - e.g. subject{' '}
          <Example>{'Quick question for {{company_name}}'}</Example>.
        </>
      ),
      done: sequenceCount > 0,
      progress: sequenceCount ? `${sequenceCount} written` : null,
      to: '/sequences/new',
      button: 'Write an email',
    },
    {
      title: 'Start a campaign',
      text: 'Create a campaign, pick the email you wrote, add your prospects and an inbox to send from, then press Start sending. It sends a few emails at a time during business hours, so you never look like a spammer.',
      done: counts.campaigns > 0,
      progress: counts.campaigns ? `${counts.campaigns} campaign${counts.campaigns === 1 ? '' : 's'}` : null,
      to: '/campaigns/new',
      button: 'Create a campaign',
    },
    {
      title: 'Answer the replies',
      text: 'When someone writes back, it shows up in Lead Box. Reply from there. The campaign automatically stops emailing anyone who has replied.',
      done: counts.emails_logged > 0,
      progress: counts.emails_logged ? `${counts.emails_logged} emails sent so far` : null,
      to: '/leadbox',
      button: 'Open Lead Box',
    },
  ]

  const doneCount = steps.filter((s) => s.done).length
  const nextIndex = steps.findIndex((s) => !s.done)

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">How to use Outbound</h1>
        <p className="mt-2 text-gray-600">
          Example: <strong>email web design studios and book calls with them.</strong> Do these 6 steps once. After that,
          every new campaign is just steps 2-5.
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-gray-900">
            {doneCount === steps.length ? "You're all set up" : `${doneCount} of ${steps.length} done`}
          </span>
          {nextIndex >= 0 && <span className="text-gray-500">Next: {steps[nextIndex].title}</span>}
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-200">
          <div className="h-full rounded-full bg-primary-600 transition-all" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
        </div>
      </div>

      <ol className="space-y-3">
        {steps.map((step, i) => {
          const isNext = i === nextIndex
          return (
            <li key={step.title}>
              <Card className={isNext ? 'ring-2 ring-primary-500' : ''}>
                <div className="flex gap-4">
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                      step.done ? 'bg-green-100 text-green-700' : isNext ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-500'
                    }`}
                    aria-label={step.done ? 'Done' : `Step ${i + 1}`}
                  >
                    {step.done ? <CheckIcon className="h-5 w-5" /> : i + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <h2 className={`text-lg font-medium ${step.done ? 'text-gray-500' : 'text-gray-900'}`}>{step.title}</h2>
                      {step.progress && <span className="text-xs text-green-700">✓ {step.progress}</span>}
                    </div>
                    <p className="mt-1 text-sm leading-relaxed text-gray-600">{step.text}</p>
                    <Link
                      to={step.to}
                      className={`mt-3 inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium ${
                        isNext
                          ? 'bg-primary-600 text-white hover:bg-primary-700'
                          : 'border border-gray-200 text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      {step.button}
                      <ArrowRightIcon className="h-4 w-4" />
                    </Link>
                  </div>
                </div>
              </Card>
            </li>
          )
        })}
      </ol>

      <details className="rounded-card bg-white p-5">
        <summary className="cursor-pointer text-sm font-medium text-gray-700">Optional extras</summary>
        <ul className="mt-3 space-y-2 text-sm text-gray-600">
          <li>
            <Link to="/verifier" className="font-medium text-primary-700 hover:underline">Verifier</Link> - check the emails
            are real before sending, so fewer bounce.
          </li>
          <li>
            <Link to="/personalizer" className="font-medium text-primary-700 hover:underline">Personalizer</Link> - let AI
            write a personal first line for each person.
          </li>
          <li>
            <Link to="/warmup" className="font-medium text-primary-700 hover:underline">Warmup</Link> - see how many of your
            emails land in the inbox instead of spam.
          </li>
          <li>
            <Link to="/scrapers" className="font-medium text-primary-700 hover:underline">Google Maps or Clutch</Link> - other
            places to find businesses (Google Maps needs a Google API key; the page shows how).
          </li>
        </ul>
      </details>
    </div>
  )
}
