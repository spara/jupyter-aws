from pulumi import export, ResourceOptions
import pulumi_aws as aws
import pulumi_random as random
import json

ecs_cluster = aws.ecs.Cluster('cluster')

default_vpc = aws.ec2.get_vpc(default=True)
default_vpc_subnets = aws.ec2.get_subnet_ids(vpc_id=default_vpc.id)

random_string = random.RandomString("randomString",
    length=8,
    special=False)

ecs_task_execution_role = aws.iam.Role("ecsTaskExecutionRole", assume_role_policy="""{
"Version": "2012-10-17",
"Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
""")

amazon_ecs_task_execution_role_policy = aws.iam.get_policy(arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")

policy_role_attachment = aws.iam.RolePolicyAttachment("policyRoleAttachment",
    role=ecs_task_execution_role.name,
    policy_arn=amazon_ecs_task_execution_role_policy.arn)

jupyter_ecs_log_group = aws.cloudwatch.LogGroup("jupyterEcsLogGroup")

jupyter_task_definition = aws.ecs.TaskDefinition("jupyterTaskDefinition",
    family=random_string.result.apply(lambda result: f"jupyter-{result}"),
    requires_compatibilities=["FARGATE"],
    network_mode="awsvpc",
    cpu=var["cpu"],
    memory=var["memory"],
    execution_role_arn=ecs_task_execution_role.arn,
    container_definitions=pulumi.Output.all(random_string.result, jupyter_ecs_log_group.name, random_string.result).apply(lambda randomStringResult, name, randomStringResult1: f"""  [
    {{
        "entryPoint": ["start-notebook.sh","--NotebookApp.token='{var["token"]}'"],
        "essential": true,
        "image": "registry.hub.docker.com/jupyter/datascience-notebook:{var["jupyter_docker_tag"]}",
        "name": "jupyter-{random_string_result}",
        "portMappings": [
            {{
                "containerPort": 8888,
                "hostPort": 8888
            }}
        ],
        "logConfiguration": {{
                "logDriver": "awslogs",
                "options": {{
                  "awslogs-region": "{var["region"]}",
                  "awslogs-group": "{name}",
                  "awslogs-stream-prefix": "{random_string_result1}"
            }}
        }}
    }}
  ]
"""))

vpc = aws.ec2.get_vpc(id=var["vpc_id"])

lb = aws.lb.get_load_balancer(arn=var["loadbalancer_arn"])

lb_listener = aws.lb.get_listener(load_balancer_arn=var["loadbalancer_arn"],
    port=443)

jupyter_target_group = aws.lb.TargetGroup("jupyterTargetGroup",
    port=80,
    protocol="HTTP",
    vpc_id=vpc.id,
    target_type="ip",
    health_check={
        "matcher": "200,302",
    })

jupyter_security_group = aws.ec2.SecurityGroup("jupyterSecurityGroup",
    vpc_id=vpc.id,
    ingress=[{
        "description": "Incoming 8888",
        "from_port": 8888,
        "to_port": 8888,
        "protocol": "tcp",
        "security_groups": lb.security_groups,
    }],
    egress=[{
        "from_port": 0,
        "to_port": 0,
        "protocol": "-1",
        "cidr_blocks": ["0.0.0.0/0"],
    }],
    tags={
        "Name": random_string.result.apply(lambda result: f"jupyter_{result}"),
    })

jupyter_service = aws.ecs.Service("jupyterService",
    cluster=ecs_cluster.id,
    task_definition=jupyter_task_definition.id,
    desired_count=1,
    launch_type="FARGATE",
    network_configuration={
        "subnets": var["fargate_subnets"],
        "security_groups": [jupyter_security_group.id],
    },
    load_balancers=[{
        "target_group_arn": jupyter_target_group.arn,
        "container_name": random_string.result.apply(lambda result: f"jupyter-{result}"),
        "containerPort": 8888,
    }],
    opts=ResourceOptions(depends_on=[jupyter_target_group]))

jupyter_lb_listener_rule = aws.lb.ListenerRule("jupyterLbListenerRule",
    listener_arn=lb_listener.arn,
    priority=%!v(PANIC=Format method: fatal: A failure has occurred: unexpected literal type in GenLiteralValueExpression: none (main.tf.pp:128,14-18)),
    actions=[{
        "type": "forward",
        "target_group_arn": jupyter_target_group.arn,
    }],
    conditions=[{
        "field": "host-header",
        "values": [random_string.result.apply(lambda result: f"jupyter-{result}.{var['domain']}")],
    }],
    opts=ResourceOptions(depends_on=[jupyter_target_group]))

jupyter_cname = aws.route53.Record("jupyterCname",
    zone_id=var["hosted_zone_id"],
    name=random_string.result.apply(lambda result: f"jupyter-{result}.{var['domain']}"),
    type="CNAME",
    records=[lb.dns_name],
    ttl=300)

pulumi.export("url", jupyter_cname.name.apply(lambda name: f"{name}?token={var['token']}"))
