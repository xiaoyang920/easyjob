FROM maven:3.9.9-eclipse-temurin-21 AS blog-build
WORKDIR /build/services/blog-service
COPY services/blog-service/pom.xml ./pom.xml
COPY contracts /build/contracts
COPY services/blog-service/src ./src
COPY auth-common /build/auth-common
COPY search-index-common /build/search-index-common
RUN cp src/main/resources/application-example.yml src/main/resources/application.yml && mvn -B -DskipTests package

FROM maven:3.9.9-eclipse-temurin-21 AS gateway-build
WORKDIR /build/services/gateway
COPY services/gateway/pom.xml ./pom.xml
COPY services/gateway/src ./src
COPY auth-common /build/auth-common
COPY deploy/gateway.yml src/main/resources/application.yml
RUN mvn -B -DskipTests package

FROM maven:3.9.9-eclipse-temurin-21 AS auth-build
WORKDIR /build/services/auth-service
COPY services/auth-service/pom.xml ./pom.xml
COPY services/auth-service/src ./src
COPY auth-common /build/auth-common
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m app
WORKDIR /app
USER 10001

FROM runtime AS blog
COPY --from=blog-build /build/services/blog-service/target/easyjob-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM runtime AS gateway
COPY --from=gateway-build /build/services/gateway/target/*.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM runtime AS auth
COPY --from=auth-build /build/services/auth-service/target/easyjob-auth-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM maven:3.9.9-eclipse-temurin-21 AS excel-build
WORKDIR /build/services/excel-service
COPY services/excel-service/pom.xml ./pom.xml
COPY services/excel-service/src ./src
RUN mvn -B -DskipTests package

FROM runtime AS excel
USER root
RUN install -d -o 10001 -g 10001 /app/exports
USER 10001
COPY --from=excel-build /build/services/excel-service/target/easyjob-excel-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM maven:3.9.9-eclipse-temurin-21 AS search-index-build
WORKDIR /build/services/search-index-service
COPY services/search-index-service/pom.xml ./pom.xml
COPY services/search-index-service/src ./src
COPY search-index-common /build/search-index-common
RUN mvn -B -DskipTests package

FROM runtime AS search-index
COPY --from=search-index-build /build/services/search-index-service/target/easyjob-search-index-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]
