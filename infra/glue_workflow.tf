# Encadena todo el pipeline crawler raw -> Job1 -> crawlers processed+quarantine
# en paralelo -> Job2 -> crawler curated como un único Glue Workflow. El trigger
# de arranque es ON_DEMAND, lo dispara el Lambda de orchestration.tf al llegar
# un archivo nuevo a raw/, vía `start_workflow_run`

resource "aws_glue_workflow" "pipeline" {
  name        = "${var.project_name}-pipeline"
  description = "raw -> standardize -> processed/quarantine -> enrich -> curated, con catalogación en cada zona"
}

resource "aws_glue_trigger" "start" {
  name          = "${var.project_name}-start"
  type          = "ON_DEMAND"
  workflow_name = aws_glue_workflow.pipeline.name

  actions {
    crawler_name = aws_glue_crawler.raw.name
  }
}

resource "aws_glue_trigger" "after_raw_crawler" {
  name          = "${var.project_name}-after-raw-crawler"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name

  actions {
    job_name = aws_glue_job.standardize.name
  }

  predicate {
    conditions {
      crawler_name = aws_glue_crawler.raw.name
      crawl_state  = "SUCCEEDED"
    }
  }
}

resource "aws_glue_trigger" "after_standardize" {
  name          = "${var.project_name}-after-standardize"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name

  actions {
    crawler_name = aws_glue_crawler.processed.name
  }
  actions {
    crawler_name = aws_glue_crawler.quarantine.name
  }

  predicate {
    conditions {
      job_name = aws_glue_job.standardize.name
      state    = "SUCCEEDED"
    }
  }
}

resource "aws_glue_trigger" "after_processed_and_quarantine_crawlers" {
  name          = "${var.project_name}-after-processed-quarantine"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name

  actions {
    job_name = aws_glue_job.enrich_curated.name
  }

  predicate {
    logical = "AND"

    conditions {
      crawler_name = aws_glue_crawler.processed.name
      crawl_state  = "SUCCEEDED"
    }
    conditions {
      crawler_name = aws_glue_crawler.quarantine.name
      crawl_state  = "SUCCEEDED"
    }
  }
}

resource "aws_glue_trigger" "after_enrich_curated" {
  name          = "${var.project_name}-after-enrich-curated"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name

  actions {
    crawler_name = aws_glue_crawler.curated.name
  }

  predicate {
    conditions {
      job_name = aws_glue_job.enrich_curated.name
      state    = "SUCCEEDED"
    }
  }
}
