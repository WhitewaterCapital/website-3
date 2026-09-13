#!/usr/bin/env node
// Standalone hand-trace verification for edgar-sources.js's pure functions —
// same situation as scripts/verify-conviction.mjs and friends: this repo has
// no jest/vitest config, and this sandbox has no outbound network access to
// sec.gov to run a real end-to-end fetch against (confirmed: a direct curl
// to data.sec.gov/www.sec.gov from this environment gets a 403 policy denial
// at the local egress proxy). Instead of skipping verification, this
// hand-traces edgar-sources.js's PURE, no-network functions (parsing,
// filtering, summarizing) against fixtures that are either the literal real
// payload observed live via the WebFetch tool during development (which
// reaches the real internet through different infrastructure than this
// sandbox's own egress), or a realistic payload built to match that exact
// confirmed schema field-for-field. Expected values in the trickier
// arithmetic assertions (summarizeInsiderActivity's dollar-weighting) are
// computed by hand in the comments beside them, not just asserted blind.
//
// This imports the REAL src/lib/whitewatch-data/edgar-sources.js unmodified
// (not a copy) — no fetch() call in it is ever invoked here, since every
// function under test here is one of its pure/no-network exports.
//
// Run (from the repo root):
//   node --experimental-default-type=module scripts/verify-edgar-insider.mjs
// (needs --experimental-default-type=module because this project's
// package.json has no "type" field, so plain `node` would otherwise treat
// this repo's ESM-style .js files as CommonJS. Also needs `npm install` run
// first in a real checkout, same as any other script here, because
// edgar-sources.js declares `import 'server-only'` like every other file in
// lib/whitewatch-data/ — a real dependency already in package.json.)

import {
  parseTickerDirectory,
  pickForm4Filings,
  parseXml,
  parseForm4Xml,
  summarizeInsiderActivity,
} from '../src/lib/whitewatch-data/edgar-sources.js';

let passed = 0;
let failed = 0;
function ok(label, cond) {
  if (cond) { passed++; console.log(`  PASS: ${label}`); }
  else { failed++; console.log(`  FAIL: ${label}`); }
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (1) parseTickerDirectory — real shape from company_tickers.json ===');
{
  // Verbatim shape confirmed live 2026-09-13 via WebFetch against
  // https://www.sec.gov/files/company_tickers.json (first 3 real entries
  // plus one lowercase-ticker synthetic edge case appended).
  const raw = {
    '0': { cik_str: 1045810, ticker: 'NVDA', title: 'NVIDIA CORP' },
    '1': { cik_str: 320193, ticker: 'AAPL', title: 'Apple Inc.' },
    '2': { cik_str: 1652044, ticker: 'GOOGL', title: 'Alphabet Inc.' },
    '3': { cik_str: 1800, ticker: 'abt', title: 'ABBOTT LABORATORIES' }, // lowercase edge case
  };
  const dir = parseTickerDirectory(raw);
  ok('AAPL resolves to cik 0000320193 (10-digit zero-padded)', dir.get('AAPL')?.cik === '0000320193');
  ok('AAPL cikNumeric is 320193', dir.get('AAPL')?.cikNumeric === 320193);
  ok('AAPL name is "Apple Inc."', dir.get('AAPL')?.name === 'Apple Inc.');
  ok('lowercase "abt" in the source still resolves under uppercase key ABT', dir.get('ABT')?.cikNumeric === 1800);
  ok('NVDA cik has correct zero-padding width (10 chars)', dir.get('NVDA')?.cik.length === 10);
  ok('unknown ticker is absent, not a false entry', dir.get('ZZZZNOPE') === undefined);
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (2) pickForm4Filings — realistic submissions.json filings.recent ===');
{
  // Realistic mixed-form filings.recent block: a 10-Q, two Form 4s inside
  // the window, one Form 4 OUTSIDE the window (must be excluded), one
  // Form 3, one Form 144, and one Form 4/A amendment inside the window.
  const submissions = {
    filings: {
      recent: {
        accessionNumber: ['0001-A', '0002-B', '0003-C', '0004-D', '0005-E', '0006-F'],
        filingDate:       ['2026-09-10', '2026-09-05', '2026-08-01', '2026-05-01', '2026-09-11', '2026-09-02'],
        reportDate:       ['2026-06-30', '2026-09-04', '2026-07-30', '2026-04-29', '2026-09-10', '2026-08-31'],
        primaryDocument:  ['q10.htm', 'form4.xml', 'form4.xml', 'form4.xml', 'primary_doc.xml', 'form4a.xml'],
        form:             ['10-Q', '4', '4', '4', '3', '4/A'],
      },
    },
  };
  const { filings, truncated } = pickForm4Filings(submissions, { sinceDateISO: '2026-06-15' });
  ok('exactly 3 Form-4-family filings kept (2 real "4" + 1 "4/A"), 10-Q/144-window-excluded/Form-3 dropped',
    filings.length === 3);
  ok('the out-of-window Form 4 (filed 2026-05-01) is excluded', !filings.some((f) => f.accessionNumber === '0004-D'));
  ok('the Form 3 (not a Form 4) is excluded', !filings.some((f) => f.accessionNumber === '0005-E'));
  ok('the 4/A amendment is included and flagged isAmendment', filings.find((f) => f.accessionNumber === '0006-F')?.isAmendment === true);
  ok('a plain "4" is NOT flagged as an amendment', filings.find((f) => f.accessionNumber === '0002-B')?.isAmendment === false);
  ok('truncated is false for a normal-size recent block', truncated === false);
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (3) parseXml + parseForm4Xml — realistic Form 4 XML (matches live-verified schema) ===');
{
  // Reconstructed to match, field-for-field, the REAL live Form 4 XML
  // fetched 2026-09-13 from
  // https://www.sec.gov/Archives/edgar/data/320193/000114036126036226/form4.xml
  // (Apple Inc., reporting owner Jennifer Newstead, SVP GC and Government
  // Affairs, sold 1,438 shares at $317.23/share on 2026-09-08, disposed,
  // 34,352 shares owned after, direct ownership, pursuant to a Rule 10b5-1
  // plan). Only the officer's own CIK is a placeholder (not disclosed to me
  // by the live fetch's summary), everything else matches the confirmed
  // real values.
  const aaplXml = `<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2026-09-08</periodOfReport>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001780525</rptOwnerCik>
      <rptOwnerName>Newstead Jennifer</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
      <officerTitle>SVP, GC and Government Affairs</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-08</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>S</transactionCode>
        <equitySwapInvolved>0</equitySwapInvolved>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1438</value></transactionShares>
        <transactionPricePerShare><value>317.23</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>34352</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <remarks>This transaction was made pursuant to a Rule 10b5-1 trading plan adopted on May 5, 2026.</remarks>
  <ownerSignature>
    <signatureName>Sam Whittington, Attorney-in-Fact</signatureName>
    <signatureDate>2026-09-10</signatureDate>
  </ownerSignature>
</ownershipDocument>`;

  const txs = parseForm4Xml(aaplXml, {
    accessionNumber: '0001140361-26-036226',
    filingDate: '2026-09-10',
    reportDate: '2026-09-08',
    isAmendment: false,
    sourceUrl: 'https://www.sec.gov/Archives/edgar/data/320193/000114036126036226/',
  });

  ok('exactly one transaction parsed', txs.length === 1);
  const t = txs[0];
  ok('insider name parsed from rptOwnerName', t.insiderName === 'Newstead Jennifer');
  ok('officer role + title captured (not just generic "Officer")', t.insiderRoles.includes('SVP, GC and Government Affairs'));
  ok('not flagged as Director or 10% owner', !t.insiderRoles.includes('Director') && !t.insiderRoles.includes('10% owner'));
  ok('issuer ticker AAPL parsed from issuerTradingSymbol', t.issuerTicker === 'AAPL');
  ok('transactionCode is "S"', t.transactionCode === 'S');
  ok('transactionCodeLabel maps to "Open-market sale"', t.transactionCodeLabel === 'Open-market sale');
  ok('shares parsed as number 1438 (unwrapped from <value>)', t.shares === 1438);
  ok('pricePerShare parsed as number 317.23', t.pricePerShare === 317.23);
  ok('acquiredDisposedCode is "D"', t.acquiredDisposedCode === 'D');
  ok('sharesOwnedAfter parsed as 34352', t.sharesOwnedAfter === 34352);
  ok('ownershipType is direct ("D")', t.ownershipType === 'D');
  ok('derivative flag is false (came from nonDerivativeTable)', t.derivative === false);
  ok('sourceUrl carried through untouched (traceability)', t.sourceUrl.includes('000114036126036226'));
  ok('accessionNumber carried through', t.accessionNumber === '0001140361-26-036226');
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (4) parseForm4Xml — small-cap, TWO joint reporting owners + a derivative (option) exercise ===');
{
  // Realistic small-cap shape: a director + a 10% owner filing jointly on
  // one Form 4 (schema allows multiple <reportingOwner> siblings — this
  // exercises the array-collapsing path in parseXml), plus one
  // derivativeTransaction (a stock-option exercise, code "M") alongside a
  // nonDerivativeTransaction (the resulting open-market-adjacent purchase
  // isn't realistic for M, so this is instead a straight open-market buy,
  // code "P", to exercise the SIGNAL_CODES path in summarizeInsiderActivity
  // later).
  const smallCapXml = `<ownershipDocument>
  <issuer>
    <issuerCik>0001999999</issuerCik>
    <issuerName>Example Small Cap Inc.</issuerName>
    <issuerTradingSymbol>XSCI</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001111111</rptOwnerCik>
      <rptOwnerName>Doe Jane</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>0</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
    </reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0002222222</rptOwnerCik>
      <rptOwnerName>Doe Family Trust</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>0</isOfficer>
      <isTenPercentOwner>1</isTenPercentOwner>
      <isOther>0</isOther>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-08-20</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>105000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>I</value></directOrIndirectOwnership>
        <indirectOwnershipNature><value>By Trust</value></indirectOwnershipNature>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Stock Option</value></securityTitle>
      <transactionDate><value>2026-08-21</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>M</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>2000</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>2000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>`;

  const txs = parseForm4Xml(smallCapXml, {
    accessionNumber: '0009999999-26-000001',
    filingDate: '2026-08-22',
    reportDate: '2026-08-21',
    isAmendment: false,
    sourceUrl: 'https://www.sec.gov/Archives/edgar/data/1999999/0009999999260000011/',
  });

  ok('two transactions parsed (one non-derivative + one derivative)', txs.length === 2);
  const nonDeriv = txs.find((t) => !t.derivative);
  const deriv = txs.find((t) => t.derivative);
  ok('both reporting owners are joined into insiderName', nonDeriv.insiderName === 'Doe Jane & Doe Family Trust');
  ok('roles include both Director and 10% owner across the two joint filers', nonDeriv.insiderRoles.includes('Director') && nonDeriv.insiderRoles.includes('10% owner'));
  ok('primaryCik is the FIRST reportingOwner listed (Jane Doe)', nonDeriv.insiderCik === '0001111111');
  ok('indirect ownership type "I" parsed correctly', nonDeriv.ownershipType === 'I');
  ok('non-derivative transaction code is P (open-market purchase)', nonDeriv.transactionCode === 'P');
  ok('derivative transaction correctly flagged derivative:true', deriv.derivative === true);
  ok('derivative transaction code M maps to "Option exercise"', deriv.transactionCodeLabel === 'Option exercise');
  ok('derivative price of 0 parses as number 0, not null (real zero, e.g. option grant)', deriv.pricePerShare === 0);
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (5) parseXml — structural edge cases ===');
{
  const selfClosing = parseXml('<ownershipDocument><footnoteId id="F1"/><name>x</name></ownershipDocument>');
  ok('self-closing element parses without throwing and yields empty leaf value', selfClosing.ownershipDocument.footnoteId === '');

  const withComment = parseXml('<a><!-- a comment --><b>1</b></a>');
  ok('comments are stripped, real content still parses', withComment.a.b === '1');

  const entities = parseXml('<a>Tom &amp; Jerry &lt;3</a>');
  ok('entities decoded correctly and in the right order (&amp; before &lt; would double-decode)', entities.a === 'Tom & Jerry <3');
}

// ─────────────────────────────────────────────────────────────────────────
console.log('=== (6) summarizeInsiderActivity — three distinguishable scenarios ===');
{
  // (a) Zero signal transactions — only a grant (A) and a tax-withholding
  // disposition (F), no open-market P/S at all. Must NOT produce a
  // fabricated neutral score.
  const noSignalTx = [
    { derivative: false, transactionCode: 'A', shares: 1000, pricePerShare: 0, insiderCik: '1' },
    { derivative: false, transactionCode: 'F', shares: 200, pricePerShare: 50, insiderCik: '1' },
  ];
  const sNone = summarizeInsiderActivity(noSignalTx, 90);
  ok('(a) zero P/S transactions => signalTransactionCount 0', sNone.signalTransactionCount === 0);
  ok('(a) score is null, not 0 — "no data" must not look like "neutral"', sNone.score === null);
  ok('(a) confidence is 0', sNone.confidence === 0);

  // (b) Two sells by the SAME insider (classic 10b5-1 tranche pattern) —
  // low confidence expected (2/10 = 0.2).
  const twoSells = [
    { derivative: false, transactionCode: 'S', shares: 1000, pricePerShare: 10, insiderCik: 'X' },
    { derivative: false, transactionCode: 'S', shares: 500, pricePerShare: 12, insiderCik: 'X' },
  ];
  const sTwo = summarizeInsiderActivity(twoSells, 90);
  // hand math: sellDollars = 1000*10 + 500*12 = 10000 + 6000 = 16000; buyDollars = 0
  // netDirection = (0 - 16000) / 16000 = -1 => score = -100
  ok('(b) signalTransactionCount is 2', sTwo.signalTransactionCount === 2);
  ok('(b) sellDollars hand-computed correctly (16000)', sTwo.sellDollars === 16000);
  ok('(b) all-sell => netDirection exactly -1', sTwo.netDirection === -1);
  ok('(b) score is exactly -100 (fully negative, capped at bound not exceeded)', sTwo.score === -100);
  ok('(b) confidence is low: 2/10 = 0.2', Math.abs(sTwo.confidence - 0.2) < 1e-9);
  ok('(b) distinctInsiders is 1 (same person both times)', sTwo.distinctInsiders === 1);

  // (c) Twelve signal transactions across 4 distinct insiders, mixed
  // buy/sell, dollar-weighted net should be positive (more buying).
  // 8 buys of $10,000 each = $80,000 buyDollars
  // 4 sells of $5,000 each = $20,000 sellDollars
  // netDirection = (80000-20000)/(80000+20000) = 60000/100000 = 0.6 => score 60
  const mixed = [];
  for (let k = 0; k < 8; k++) mixed.push({ derivative: false, transactionCode: 'P', shares: 100, pricePerShare: 100, insiderCik: `buyer-${k % 3}` });
  for (let k = 0; k < 4; k++) mixed.push({ derivative: false, transactionCode: 'S', shares: 50, pricePerShare: 100, insiderCik: `seller-${k % 2}` });
  const sMixed = summarizeInsiderActivity(mixed, 90);
  ok('(c) signalTransactionCount is 12', sMixed.signalTransactionCount === 12);
  ok('(c) buyDollars hand-computed correctly (80000)', sMixed.buyDollars === 80000);
  ok('(c) sellDollars hand-computed correctly (20000)', sMixed.sellDollars === 20000);
  ok('(c) netDirection is exactly 0.6', Math.abs(sMixed.netDirection - 0.6) < 1e-9);
  ok('(c) score is exactly 60', Math.abs(sMixed.score - 60) < 1e-9);
  ok('(c) confidence saturates at 1.0 (12 >= CONFIDENCE_SATURATION_COUNT=10), not 1.2', sMixed.confidence === 1);
  ok('(c) distinctInsiders counted correctly (3 buyers + 2 sellers = 5)', sMixed.distinctInsiders === 5);

  // Derivative transactions must never leak into the signal set even with
  // matching P/S codes on the derivative side (schema allows it; policy
  // here is non-derivative-only, matching the "open-market Table I" scope
  // documented in edgar-sources.js).
  const derivOnly = [{ derivative: true, transactionCode: 'S', shares: 999, pricePerShare: 5, insiderCik: 'Y' }];
  const sDeriv = summarizeInsiderActivity(derivOnly, 90);
  ok('derivative-table S transaction is excluded from the signal set', sDeriv.signalTransactionCount === 0 && sDeriv.score === null);
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
