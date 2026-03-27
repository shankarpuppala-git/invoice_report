# invoice_report
FastAPI service that generates invoice reports — fetches credit-card orders from PostgreSQL, resolves transaction statuses via Authorize.net, and returns a formatted Excel 
workbook on demand.

A production-grade Python/FastAPI microservice that automates the generation 
of Betts Truck Parts invoice reconciliation reports.

Given a date range and application name, the service:
  • Resolves the tenant from the application registry
  • Fetches invoiced credit-card orders from the database
  • Bulk-resolves user emails via auth_users in a single query
  • Enriches each order with Authorize.net transaction status (parallel HTTP calls)
  • Returns a fully formatted Excel workbook as a direct file download

Built with FastAPI · PostgreSQL (psycopg2 pool) · openpyxl · httpx
