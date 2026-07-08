pipeline {
    agent any

    options {
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        SERVICE_NAME = 'campuscart-microservices'
        SHORT_SHA   = "${env.GIT_COMMIT?.take(7) ?: 'unknown'}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                echo $SHORT_SHA
            }
        }
        stage('Prove We Are Really Here') {
            steps {
                sh 'pwd'
                sh 'ls -la'
                sh 'git log -1 --oneline'
            }
        }
        stage('Look At auth-service') {
            steps {
                sh 'cat auth-service/Dockerfile | head -5'
            }
        }
    }

    post {
        success {
            echo 'First real pipeline. First real green build.'
        }
    }
}
