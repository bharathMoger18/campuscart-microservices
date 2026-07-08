pipeline {
    agent any

    options {
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
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
