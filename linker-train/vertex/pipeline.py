"""Vertex AI pipeline: train the linker, score it against every saved method, and promote it to the
serving folder only if it passes the gate (beats hybrid search on the frozen test set and is no
worse than the model now served).

    uv run --group pipeline python vertex/pipeline.py --image IMAGE_URI            # compile and run
    uv run --group pipeline python vertex/pipeline.py --image IMAGE_URI --compile-only

Every step runs the linker-train image, the same one `vertex/submit.sh` trains with, and reads and
writes the bucket through Vertex's /gcs/ mount. The served model is gs://BUCKET/serving/linker/;
`api-service/cloudrun/deploy.sh` builds the API from it.
"""

import argparse
import os
import time

from kfp import compiler, dsl

PROJECT = os.environ.get("GCP_PROJECT", "ac215-undersigned")
REGION = os.environ.get("REGION", "us-central1")
BUCKET = os.environ.get("BUCKET", "ac215-undersigned-data")
IMAGE = "linker-train"  # replaced by --image before compiling


def build(image: str, gpu: bool):
    data = f"gs://{BUCKET}/linking"
    runs = f"/gcs/{BUCKET}/linker-runs"

    @dsl.container_component
    def train(run_name: str, epochs: int, wandb_key: str):
        return dsl.ContainerSpec(
            image=image,
            command=["sh", "-c"],
            args=[
                f'WANDB_API_KEY="$2" python src/main.py --data {data} train --mode in '
                f'--out {runs}/"$0" --name "$0" --set epochs="$1" --tag pipeline',
                run_name,
                epochs,
                wandb_key,
            ],
        )

    @dsl.container_component
    def report(run_name: str):
        return dsl.ContainerSpec(
            image=image,
            command=["sh", "-c"],
            args=[
                f'python src/main.py --data {data} report --runs {runs}/"$0" --out {runs}/"$0"/report',
                run_name,
            ],
        )

    @dsl.container_component
    def promote(run_name: str):
        return dsl.ContainerSpec(
            image=image,
            command=["sh", "-c"],
            args=[
                f'python src/main.py --data {data} promote --run {runs}/"$0" '
                f"--serve /gcs/{BUCKET}/serving/linker",
                run_name,
            ],
        )

    @dsl.pipeline(name="undersigned-linker", description="Train, score and gate the section linker")
    def pipeline(run_name: str, epochs: int = 4, wandb_key: str = ""):
        t = train(run_name=run_name, epochs=epochs, wandb_key=wandb_key)
        t.set_display_name("train").set_cpu_limit("16").set_memory_limit("60G")
        if gpu:
            t.set_accelerator_type("NVIDIA_TESLA_T4").set_accelerator_limit(1)
        r = report(run_name=run_name).after(t)
        r.set_display_name("evaluate").set_cpu_limit("4").set_memory_limit("16G")
        p = promote(run_name=run_name).after(r)
        p.set_display_name("gate and promote").set_cpu_limit("4").set_memory_limit("16G")

    return pipeline


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="linker-train image in Artifact Registry")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--gpu", action="store_true", help="train on a T4 (needs GPU quota)")
    ap.add_argument("--compile-only", action="store_true")
    ap.add_argument("--out", default="vertex/pipeline.json")
    args = ap.parse_args()
    compiler.Compiler().compile(build(args.image, args.gpu), args.out)
    print("compiled", args.out)
    if args.compile_only:
        return
    from google.cloud import aiplatform

    aiplatform.init(project=PROJECT, location=REGION, staging_bucket=f"gs://{BUCKET}/pipeline-root")
    name = f"linker-{time.strftime('%m%d-%H%M')}"
    job = aiplatform.PipelineJob(
        display_name=name,
        template_path=args.out,
        pipeline_root=f"gs://{BUCKET}/pipeline-root",
        parameter_values={
            "run_name": name,
            "epochs": args.epochs,
            "wandb_key": os.environ.get("WANDB_API_KEY", ""),
        },
        enable_caching=False,
    )
    job.submit()
    print("submitted", job.resource_name)
    print(f"https://console.cloud.google.com/vertex-ai/pipelines/runs?project={PROJECT}")


if __name__ == "__main__":
    main()
