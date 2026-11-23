import sys, yaml, concurrent.futures as cf
sys.path.insert(0, "scripts"); sys.path.insert(0, ".")
import importlib.util
spec = importlib.util.spec_from_file_location("vb", "scripts/validate_boards.py")
src = open("scripts/validate_boards.py").read().split("tasks=")[0]   # reuse chk()
ns = {}; exec(src, ns); chk = ns["chk"]
NAMES = """sarvamai krutrim gnani observeai yellowai uniphore wadhwaniai fractal tredence mindtickle freshworks zoho chargebee browserstack hasura postman razorpay phonepe cred groww meesho swiggy zomato dream11 sharechat pocketfm cleartax unacademy upgrad oyo ola flipkart nykaa lenskart pinelabs slice jar navi kreditbee moneyview paytm paytmmoney zeta juspay setu cashfree mobikwik lendingkart policybazaar acko digit cars24 spinny urbancompany dunzo rapido porter delhivery shiprocket licious bigbasket udaan zetwerk infra.market jumbotail ofbusiness vedantu physicswallah toppr byjus eruditus simplilearn greatlearning scaler coding-ninjas leadsquared netcore clevertap moengage webengage sprinklr whatfix highradius icertis druva ittiam amagi innovaccer qure.ai niramai sigtuple artivatic perfios finbox m2p yubi cloudsek sprinto scaleup zluri atlan hevo rudderstack gupshup kaleyra exotel knowlarity haptik verloop skit.ai voicemod
turing deel remote oysterhr rippling gusto toptal andela crossover upwork fiverr
openai anthropic cohere mistral huggingface perplexity scaleai snorkelai labelbox weightsandbiases wandb replicate modal lambdalabs coreweave togetherai fireworks anyscale baseten runpod vast determined arize comet neptune dagshub clearml iterative dvc pinecone weaviate qdrant chroma milvus zilliz langchain llamaindex crewai autogen composio e2b browserbase browseruse
databricks snowflake confluent elastic mongodb couchbase cockroachlabs timescale clickhouse planetscale neon supabase vercel netlify cloudflare fastly datadog newrelic grafana honeycomb sentry pagerduty
atlassian gitlab github jfrog hashicorp docker sourcegraph postman kong
stripe plaid brex ramp mercury coinbase kraken chainalysis circle fireblocks
airbnb uber lyft doordash instacart robinhood affirm klarna wise revolut monzo nubank
nvidia amd intel qualcomm arm cerebras groq sambanova graphcore tenstorrent
samsara anduril palantir shield-ai helsing
twilio sendbird messagebird bandwidth vonage 8x8 ringcentral
toast squarespace wix canva figma miro notion airtable asana clickup monday smartsheet
intercom zendesk hubspot salesforce freshdesk gorgias gong outreach salesloft clari
bytedance tiktok sea grab gojek tokopedia traveloka shopee lazada
 zepto zeptonow juspay sprinklr upgrad haptik gupshup slice jar navi lenskart nykaa myntra urbancompany licious pharmeasy practo cars24 spinny ola olaelectric rapido porter delhivery shiprocket clevertap moengage webengage whatfix leadsquared zenoti icertis druva pubmatic innovaccer qureai sigtuple niramai curefit unacademy byjus vedantu physicswallah eightfold hevodata rudderstack apna bharatpe mobikwik lendingkart kreditbee moneyview zestmoney perfios signzy idfy digio setu cashfree pinelabs khatabook zerodha upstox smallcase angelone policybazaar acko cleartax zoomcar ather simplilearn scaler newtonschool thoughtworks nagarro thoughtspot netskope zscaler nutanix sumologic coupa bhargavi inmobi vwo wingify capillary capillarytech netcore exotel knowlarity kissflow zluri hackerearth hackerrank codenation crio masaischool agodaindia agoda makemytrip ixigo cleartrip oyo treebo sirionlabs yubi cred-club dunzo phonepe-india amex-india rubrik okta paytm razorpayx mpl games24x7 nazara zupee winzo sharechat moj glance inshorts dailyhunt pocketfm kukufm stage mxplayer hotstar jiocinema tataneu bigbasket tata1mg tatadigital tatacapital kotak hdfc icici axisbank bajajfinserv phonepay uniphore verloop skit-ai skit conversely seekho vahan finbox credgenics ringcentral-india freshworks-india mindtickle-india quantiphi tiger-analytics tigeranalytics latentview mu-sigma musigma sigmoid course5 affine absolutdata gramener lti ltimindtree mphasis persistent coforge hexaware zensar cyient
 fibe earlysalary moneytap jupiter jupitermoney epifi fi-money niyo uni-cards fplabs onecard lazypay simpl open-money yubi vayana indifi oxyzo capitalfloat neogrowth ayefinance ugrocapital progcap flexiloans kissht stashfin truebalance paysense mintoak billdesk payu ccavenue instamojo easebuzz cashfree-payments razorpay-india pinelabs-india phonepe-pvt-ltd groww-india zerodha-tech smallcase-tech finbox-in credgenics-in perfios-software signzy-technologies idfy-in digio-in setu-co m2p m2pfintech yap fyers dhan-hq paytm-money mintoak-innovations jocata clix clixcapital aavas hero-fincorp poonawalla poonawallafincorp bajaj-finance piramal piramalfinance l-and-t-finance mahindra-finance muthoot shriram-finance iifl kotak-mahindra hdfc-bank icici-bank axis-bank yesbank idfcfirst indusind federalbank rbl-bank bandhan sbi-cards amex jpmorgan goldmansachs morganstanley americanexpress mastercard visa paypal fiserv jackhenry fico experian equifax transunion cibil crif-high-mark crif bureau decentro leegality
 composio emergent rocket lightning simplismart nurix smallestai pulse dashtoon bolna vapi dhiway healthifyme mykaarma neysa soket sprinto scribe truefoundry tensorlake lamatic maxim mem0 portkey langfuse helicone relevanceai sierra decagon glean hebbia harvey writer jasper typeface lindy ema 11x artisan clay unstructured llamaindex langchain pinecone weaviate qdrant chroma milvus zilliz vectara cohere-labs adept character inflection reka ai21 stability runway pika luma synthesia heygen elevenlabs deepgram assemblyai speechmatics krisp otter fireflies gong avoma fathom tldv grain read-ai rivery airbyte fivetran dbt-labs hex mode sigma-computing thoughtspot preset astronomer prefect dagster temporal inngest trigger-dev windsurf codeium cursor anysphere replit bolt stackblitz lovable v0 factory cognition poolside magic augment tabnine sourcegraph qodo codium warp zed graphite coderabbit greptile bito
""".split()
NAMES = sorted(set(n.lower() for n in NAMES))
cur = yaml.safe_load(open("config/boards.yaml"))
tasks = [(k, t) for t in NAMES for k in ("greenhouse", "lever", "ashby", "workable")]
found = {k: set(v) for k, v in cur.items()}
with cf.ThreadPoolExecutor(24) as ex:
    for r in ex.map(lambda a: chk(*a), tasks):
        if r and (r[2] or 0) > 0: found.setdefault(r[0], set()).add(r[1])
out = {k: sorted(v) for k, v in found.items()}
yaml.safe_dump(out, open("config/boards.yaml", "w"))
print({k: len(v) for k, v in out.items()}, "total", sum(len(v) for v in out.values()))
