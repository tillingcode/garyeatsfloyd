<#
.SYNOPSIS
    Deploy script for the GaryEatsFloyd application.

.DESCRIPTION
    Handles bootstrapping AWS backend resources, building Lambda packages,
    and deploying all infrastructure via Terraform.

.PARAMETER Action
    The deployment action to perform:
      bootstrap  - Create Terraform backend (S3 state bucket + DynamoDB lock table)
      plan       - Build everything + run terraform plan
      apply      - Build everything + terraform apply + deploy website to S3
      destroy    - Tear down all resources
      build      - Build Lambda packages + React website
      full       - bootstrap + build + apply + deploy website (first-time deploy)
      output     - Show terraform outputs

.PARAMETER AutoApprove
    Skip interactive approval on apply/destroy.

.PARAMETER YouTubeApiKey
    YouTube Data API key (required for plan/apply/full). Can also be set via
    environment variable YOUTUBE_API_KEY.

.EXAMPLE
    .\deploy.ps1 -Action full -YouTubeApiKey "your-key-here"

.EXAMPLE
    .\deploy.ps1 -Action plan

.EXAMPLE
    .\deploy.ps1 -Action apply -AutoApprove
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("bootstrap", "plan", "apply", "destroy", "build", "full", "output")]
    [string]$Action,

    [switch]$AutoApprove,

    [string]$YouTubeApiKey
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────────────────────────
$ProjectRoot   = $PSScriptRoot
$TerraformDir  = Join-Path $ProjectRoot "terraform"
$SrcDir        = Join-Path $ProjectRoot "src"
$DistDir       = Join-Path $ProjectRoot "dist"
$LayerDir      = Join-Path $SrcDir "layer"

$WebsiteDir    = Join-Path $ProjectRoot "website"

$AwsRegion     = "us-east-1"
$StateBucket   = "garyeatsfloyd-terraform-state"
$LockTable     = "garyeatsfloyd-terraform-locks"

$LambdaFunctions = @(
    "youtube_scanner",
    "video_downloader",
    "video_processor",
    "api_handler",
    "website_publisher"
)

# ── Helpers ────────────────────────────────────────────────────────────────────

function Write-Banner {
    param([string]$Message)
    $line = "=" * 60
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host ">> $Message" -ForegroundColor Yellow
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "Required command '$Name' not found. Please install it and ensure it is on your PATH."
    }
}

function Resolve-YouTubeApiKey {
    if ($YouTubeApiKey) { return $YouTubeApiKey }
    if ($env:YOUTUBE_API_KEY) { return $env:YOUTUBE_API_KEY }

    # Check for .env file
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*YOUTUBE_API_KEY\s*=\s*(.+)$') {
                return $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }

    return $null
}

# ── Bootstrap ──────────────────────────────────────────────────────────────────
function Invoke-Bootstrap {
    Write-Banner "Bootstrapping Terraform Backend"

    Assert-Command "aws"

    # ── S3 state bucket ──
    Write-Step "Checking S3 state bucket: $StateBucket"
    $bucketExists = $false
    try {
        aws s3api head-bucket --bucket $StateBucket --region $AwsRegion 2>$null
        $bucketExists = $true
    } catch { }

    if ($bucketExists) {
        Write-Host "  Bucket '$StateBucket' already exists. Skipping." -ForegroundColor Green
    } else {
        Write-Step "Creating S3 bucket: $StateBucket"
        aws s3api create-bucket `
            --bucket $StateBucket `
            --region $AwsRegion | Out-Null

        Write-Step "Enabling versioning"
        aws s3api put-bucket-versioning `
            --bucket $StateBucket `
            --versioning-configuration Status=Enabled `
            --region $AwsRegion

        Write-Step "Enabling server-side encryption"
        aws s3api put-bucket-encryption `
            --bucket $StateBucket `
            --server-side-encryption-configuration '{
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            }' `
            --region $AwsRegion

        Write-Step "Blocking public access"
        aws s3api put-public-access-block `
            --bucket $StateBucket `
            --public-access-block-configuration `
                "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" `
            --region $AwsRegion

        Write-Host "  Bucket created successfully." -ForegroundColor Green
    }

    # ── DynamoDB lock table ──
    Write-Step "Checking DynamoDB lock table: $LockTable"
    $tableExists = $false
    try {
        aws dynamodb describe-table --table-name $LockTable --region $AwsRegion 2>$null | Out-Null
        $tableExists = $true
    } catch { }

    if ($tableExists) {
        Write-Host "  Table '$LockTable' already exists. Skipping." -ForegroundColor Green
    } else {
        Write-Step "Creating DynamoDB lock table: $LockTable"
        aws dynamodb create-table `
            --table-name $LockTable `
            --attribute-definitions AttributeName=LockID,AttributeType=S `
            --key-schema AttributeName=LockID,KeyType=HASH `
            --billing-mode PAY_PER_REQUEST `
            --region $AwsRegion | Out-Null

        Write-Step "Waiting for table to become active..."
        aws dynamodb wait table-exists --table-name $LockTable --region $AwsRegion
        Write-Host "  Lock table created successfully." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Backend bootstrap complete!" -ForegroundColor Green
}

# ── Build ──────────────────────────────────────────────────────────────────────
function Invoke-Build {
    Write-Banner "Building Lambda Packages"

    Assert-Command "pip"

    # Create dist directory
    if (-not (Test-Path $DistDir)) {
        New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
    }

    # ── Install layer dependencies ──
    $layerPythonDir = Join-Path $LayerDir "python"
    $requirementsFile = Join-Path $SrcDir "requirements.txt"

    if (Test-Path $requirementsFile) {
        Write-Step "Installing layer dependencies from requirements.txt"

        if (Test-Path $layerPythonDir) {
            Remove-Item -Recurse -Force $layerPythonDir
        }
        New-Item -ItemType Directory -Path $layerPythonDir -Force | Out-Null

        pip install -r $requirementsFile -t $layerPythonDir --quiet --upgrade
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install layer dependencies."
        }
        Write-Host "  Layer dependencies installed." -ForegroundColor Green
    } else {
        Write-Host "  No requirements.txt found at $requirementsFile -- skipping layer build." -ForegroundColor DarkYellow
        # Ensure the layer dir exists so archive_file doesn't fail
        if (-not (Test-Path $layerPythonDir)) {
            New-Item -ItemType Directory -Path $layerPythonDir -Force | Out-Null
        }
    }

    # ── Validate function source dirs exist ──
    foreach ($fn in $LambdaFunctions) {
        $fnDir = Join-Path $SrcDir $fn
        if (-not (Test-Path $fnDir)) {
            Write-Error "Lambda source directory missing: $fnDir"
        }
        $handlerFile = Join-Path $fnDir "handler.py"
        if (-not (Test-Path $handlerFile)) {
            Write-Error "Handler file missing: $handlerFile"
        }
        Write-Host "  Validated: src/$fn/handler.py" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Build complete! Terraform archive_file will create the zips." -ForegroundColor Green
}

function Invoke-WebsiteBuild {
    Write-Banner "Building React Website"

    Assert-Command "npm"

    if (-not (Test-Path (Join-Path $WebsiteDir "package.json"))) {
        Write-Error "Website package.json not found at $WebsiteDir"
    }

    Write-Step "Installing website dependencies"
    Push-Location $WebsiteDir
    try {
        npm ci --silent
        if ($LASTEXITCODE -ne 0) { Write-Error "npm ci failed" }

        Write-Step "Building production bundle"
        npm run build
        if ($LASTEXITCODE -ne 0) { Write-Error "npm run build failed" }

        Write-Host "  Website built to website/dist/" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

function Invoke-WebsiteDeploy {
    Write-Banner "Deploying Website to S3"

    Assert-Command "aws"

    $websiteDist = Join-Path $WebsiteDir "dist"
    if (-not (Test-Path $websiteDist)) {
        Write-Error "Website dist folder not found. Run build first."
    }

    # Get the website bucket name from terraform output
    Push-Location $TerraformDir
    try {
        $websiteBucket = (terraform output -raw website_bucket 2>$null)
        $cfDistId = (terraform output -raw cloudfront_distribution_id 2>$null)
    } finally {
        Pop-Location
    }

    if (-not $websiteBucket) {
        Write-Error "Could not read website_bucket from terraform output. Has infrastructure been deployed?"
    }

    Write-Step "Syncing website files to s3://$websiteBucket"
    aws s3 sync $websiteDist "s3://$websiteBucket" `
        --delete `
        --cache-control "public, max-age=3600" `
        --region $AwsRegion

    # Set long cache on static assets
    aws s3 sync $websiteDist "s3://$websiteBucket" `
        --exclude "*" `
        --include "*.js" --include "*.css" --include "*.woff2" --include "*.svg" --include "*.png" `
        --cache-control "public, max-age=31536000, immutable" `
        --region $AwsRegion

    # Set no-cache on index.html so SPA updates propagate immediately
    aws s3 cp "$websiteDist/index.html" "s3://$websiteBucket/index.html" `
        --cache-control "no-cache, no-store, must-revalidate" `
        --content-type "text/html" `
        --region $AwsRegion

    if ($cfDistId) {
        Write-Step "Invalidating CloudFront cache ($cfDistId)"
        aws cloudfront create-invalidation `
            --distribution-id $cfDistId `
            --paths "/*" `
            --region $AwsRegion | Out-Null
        Write-Host "  CloudFront invalidation submitted." -ForegroundColor Green
    }

    Write-Host "  Website deployed successfully!" -ForegroundColor Green
}

# ── Terraform helpers ──────────────────────────────────────────────────────────
function Invoke-TerraformInit {
    Write-Step "Running terraform init"
    Push-Location $TerraformDir
    try {
        terraform init -input=false
        if ($LASTEXITCODE -ne 0) { Write-Error "terraform init failed" }
    } finally {
        Pop-Location
    }
}

function Set-TerraformEnvVars {
    # Pass sensitive variables via TF_VAR_ environment variables instead of
    # CLI -var args. Environment variables are NOT visible in process listings,
    # shell history, or CI/CD logs -- unlike -var which exposes the value.
    $apiKey = Resolve-YouTubeApiKey
    if (-not $apiKey) {
        Write-Error @"
YouTube API key not found. Provide it via one of:
  -YouTubeApiKey parameter
  YOUTUBE_API_KEY environment variable
  YOUTUBE_API_KEY=... in .env file at project root
"@
    }
    $env:TF_VAR_youtube_api_key = $apiKey
    Write-Step "Sensitive variables loaded into environment (not visible in process list)"
}

function Invoke-TerraformPlan {
    Write-Banner "Terraform Plan"
    Invoke-TerraformInit
    Set-TerraformEnvVars

    Write-Step "Running terraform plan"
    Push-Location $TerraformDir
    try {
        terraform plan -out=tfplan
        if ($LASTEXITCODE -ne 0) { Write-Error "terraform plan failed" }
    } finally {
        Pop-Location
    }
}

function Invoke-TerraformApply {
    Write-Banner "Terraform Apply"
    Invoke-TerraformInit
    Set-TerraformEnvVars

    $approveFlag = @()
    if ($AutoApprove) { $approveFlag = @("-auto-approve") }

    Write-Step "Running terraform apply"
    Push-Location $TerraformDir
    try {
        terraform apply @approveFlag
        if ($LASTEXITCODE -ne 0) { Write-Error "terraform apply failed" }

        Write-Host ""
        Write-Banner "Deployment Outputs"
        terraform output
    } finally {
        Pop-Location
    }
}

function Invoke-TerraformDestroy {
    Write-Banner "Terraform Destroy"
    Invoke-TerraformInit
    Set-TerraformEnvVars

    $approveFlag = @()
    if ($AutoApprove) { $approveFlag = @("-auto-approve") }

    Write-Host "WARNING: This will destroy ALL GaryEatsFloyd infrastructure!" -ForegroundColor Red
    if (-not $AutoApprove) {
        $confirm = Read-Host "Type 'yes' to continue"
        if ($confirm -ne "yes") {
            Write-Host "Destroy cancelled." -ForegroundColor Yellow
            return
        }
    }

    Write-Step "Running terraform destroy"
    Push-Location $TerraformDir
    try {
        terraform destroy @approveFlag
        if ($LASTEXITCODE -ne 0) { Write-Error "terraform destroy failed" }
    } finally {
        Pop-Location
    }
}

function Invoke-TerraformOutput {
    Write-Banner "Terraform Outputs"
    Push-Location $TerraformDir
    try {
        terraform output
    } finally {
        Pop-Location
    }
}

# ── Full Deploy ────────────────────────────────────────────────────────────────
function Invoke-FullDeploy {
    Write-Banner "Full Deployment -- GaryEatsFloyd"

    # Pre-flight checks
    Assert-Command "aws"
    Assert-Command "terraform"
    Assert-Command "pip"

    # Validate API key is available (without logging it)
    $apiKey = Resolve-YouTubeApiKey
    if (-not $apiKey) {
        Write-Error @"
YouTube API key is required for deployment.
Provide it via -YouTubeApiKey parameter, YOUTUBE_API_KEY env var, or .env file.
"@
    }
    # Clear from local variable immediately -- Set-TerraformEnvVars will re-resolve
    $apiKey = $null

    Invoke-Bootstrap
    Invoke-Build
    Invoke-WebsiteBuild
    Invoke-TerraformApply
    Invoke-WebsiteDeploy

    # Scrub sensitive env vars from session after deployment
    Remove-Item Env:TF_VAR_youtube_api_key -ErrorAction SilentlyContinue
    Write-Step "Sensitive environment variables cleared from session"
}

# ── Main ───────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  GaryEatsFloyd Deploy" -ForegroundColor Magenta
Write-Host "  In the style of Keith Floyd -- with a glass of red wine" -ForegroundColor DarkMagenta
Write-Host ""

switch ($Action) {
    "bootstrap" { Invoke-Bootstrap }
    "build"     { Invoke-Build; Invoke-WebsiteBuild }
    "plan"      { Invoke-Build; Invoke-WebsiteBuild; Invoke-TerraformPlan }
    "apply"     { Invoke-Build; Invoke-WebsiteBuild; Invoke-TerraformApply; Invoke-WebsiteDeploy }
    "destroy"   { Invoke-TerraformDestroy }
    "full"      { Invoke-FullDeploy }
    "output"    { Invoke-TerraformOutput }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
