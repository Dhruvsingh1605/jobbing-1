import requests, yaml, sys, concurrent.futures as cf
GH = "anthropic databricks scaleai airbnb stripe figma datadog twilio cloudflare coinbase discord gitlab mongodb elastic okta samsara instacart robinhood brex anduril postman razorpay phonepe zeta groww cred meesho swiggy juspay sarvam krutrim observeai yellowai uniphore wadhwaniai fractal tredence mindtickle freshworks zomato dream11 sharechat pocketfm cleartax chargebee browserstack hasura gojek grab sea wise revolut monzo cohere huggingface weightsandbiases pinecone anyscale togetherai fireworksai modal lambda mistral perplexity glean gong asana atlassian intercom hubspot zendesk pagerduty newrelic mixpanel amplitude segment rubrik nutanix thoughtspot sprinklr unacademy upgrad phonepe oyo ola flipkart nykaa lenskart pinelabs slice jar navi kreditbee moneyview kotak adityabirlacapital tatacapital turing deel remote gusto rippling plaid chime affirm toast squarespace reddit pinterest snap lyft doordash uber opendoor carta vercel supabase retool zapier mercury".split()
LV = "cred paytm groww meesho palantir spotify kpmg swiggy upgrad highradius whatfix zeta rapido dunzo pinelabs jar slice mindtickle observeai yellowai uniphore tekion sprinklr clari outreach netlify mistral coindcx wiz plaid binance bitso".split()
AS = "openai cohere perplexity ramp notion linear sarvam together replit deepgram elevenlabs harvey writer sierra decagon glean anysphere cursor runway lovable cognition poolside character synthesia hebbia clay vapi langchain llamaindex pinecone weaviate qdrant mem0 browserbase e2b sakana crusoe fal cartesia lindy relevanceai rox giga assembled posthog supabase resend ashby retool zapier mercury deel airtable lattice leapsome".split()
SR = "Freshworks Infosys Wipro Visa Bosch Ubisoft McDonalds AECOM Deloitte2 Experian".split()
WK = "workable huggingface bluecore tractable kaizen".split()
def chk(kind, tok):
    try:
        if kind=="greenhouse": u=f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs"
        elif kind=="lever": u=f"https://api.lever.co/v0/postings/{tok}?mode=json&limit=1"
        elif kind=="ashby": u=f"https://api.ashbyhq.com/posting-api/job-board/{tok}"
        elif kind=="smartrecruiters": u=f"https://api.smartrecruiters.com/v1/companies/{tok}/postings?limit=1"
        else: u=f"https://apply.workable.com/api/v1/widget/accounts/{tok}"
        r=requests.get(u,timeout=15)
        if r.status_code!=200: return None
        d=r.json()
        n = len(d.get("jobs",[])) if isinstance(d,dict) and "jobs" in d else (len(d) if isinstance(d,list) else d.get("totalFound",1))
        return (kind,tok,n)
    except Exception: return None
tasks=[("greenhouse",t) for t in set(GH)]+[("lever",t) for t in set(LV)]+[("ashby",t) for t in set(AS)]+[("smartrecruiters",t) for t in SR]+[("workable",t) for t in WK]
out={"greenhouse":[],"lever":[],"ashby":[],"smartrecruiters":[],"workable":[]}
with cf.ThreadPoolExecutor(16) as ex:
    for r in ex.map(lambda a: chk(*a), tasks):
        if r: out[r[0]].append(r[1])
for k in out: out[k]=sorted(out[k])
yaml.safe_dump(out, open("config/boards.yaml","w"))
print({k:len(v) for k,v in out.items()})
