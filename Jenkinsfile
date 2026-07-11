pipeline {
    agent {
        kubernetes {
            label 'build-agent'
        }
    }

    options {
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        SERVICE_NAME = 'campuscart-microservices'
        // SHORT_SHA   = "${env.GIT_COMMIT?.take(7) ?: 'unknown'}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Prove We Are Really Here') {
            steps {
                sh 'pwd'
                sh 'ls -la'
                sh 'git log -1 --oneline'
                echo "Building ${env.SERVICE_NAME} at commit ${env.GIT_COMMIT?.take(7) ?: 'unknown'}"
            }
        }
        stage('Look At auth-service') {
            steps {
                sh 'cat auth-service/Dockerfile | head -5'
            }
        }

        stage('Prove GHCR credentials Bind corrextly') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'ghcr-campuscart',
                    usernameVariable: 'GHCR_USER',
                    passwordVariable: 'GHCR_TOKEN'
                )]) {
                    sh 'echo "Bound as user: $GHCR_USER"'
                    sh 'echo "Token value: $GHCR_TOKEN" | base64'
                }
            }
        }
    }

    post {
        success {
            echo 'First real pipeline. First real green build.'
        }
    }
}
